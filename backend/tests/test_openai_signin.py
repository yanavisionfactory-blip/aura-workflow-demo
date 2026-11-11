import asyncio
import base64
import hashlib
import json
import time
from dataclasses import asdict
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.openai_signin import (
    CALLBACK_PATH,
    COOKIE_NAME,
    DISCOVERY_URL,
    ENDPOINTS,
    ISSUER,
    TRANSACTION_TTL,
    OpenAISignInClient,
    OpenAISignInConfig,
    OpenAISignInError,
    RedisSignInTransactions,
    openai_signin_router,
)

CLIENT_ID = "oaiapp_aura_test_registration"
REDIRECT = "https://aura.test/auth/openai/callback"


class MemoryRedis:
    """Models the server-side SET NX EX / GETDEL contract without network I/O."""

    def __init__(self):
        self.values = {}
        self.expiry = {}
        self.lock = asyncio.Lock()

    async def set(self, name, value, *, ex, nx):
        async with self.lock:
            if nx and name in self.values:
                return False
            self.values[name] = value
            self.expiry[name] = time.time() + ex
            return True

    async def getdel(self, name):
        async with self.lock:
            result = self.values.pop(name, None)
            expired = self.expiry.pop(name, 0) <= time.time()
            return None if expired else result


class Vault:
    def __init__(self):
        self.cipher = Fernet(Fernet.generate_key())

    def encrypt(self, value):
        return self.cipher.encrypt(json.dumps(value).encode()).decode()

    def decrypt(self, value):
        return json.loads(self.cipher.decrypt(value.encode()))


class Provider:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "openai-test-signing-key"
        self.nonce = ""
        self.claim_changes = {}
        self.missing_claims = []
        self.metadata_changes = {}
        self.token_status = 200
        self.token_payload = None
        self.token_override = None
        self.calls = []
        self.metadata = {
            **ENDPOINTS, "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
        }

    def token(self):
        claims = {
            "iss": ISSUER, "aud": [CLIENT_ID], "sub": "openai-subject-a",
            "iat": int(time.time()), "exp": int(time.time()) + 3600,
            "nonce": self.nonce, "email": "test@example.test", "email_verified": False,
            "name": "Test user", "sid": "openai-session-a", **self.claim_changes,
        }
        for name in self.missing_claims:
            claims.pop(name, None)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": self.kid})

    def respond(self, request):
        self.calls.append(request)
        if str(request.url) == DISCOVERY_URL:
            return httpx.Response(200, json={**self.metadata, **self.metadata_changes})
        if str(request.url) == ENDPOINTS["jwks_uri"]:
            key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
            return httpx.Response(200, json={"keys": [{
                **key, "kid": self.kid, "alg": "RS256", "use": "sig",
            }]})
        if str(request.url) == ENDPOINTS["token_endpoint"]:
            payload = self.token_payload if self.token_payload is not None else {
                "id_token": self.token_override or self.token(),
            }
            return httpx.Response(self.token_status, json=payload)
        raise AssertionError("Unexpected provider URL")


@pytest.fixture
async def flow():
    provider = Provider()
    transactions = RedisSignInTransactions(MemoryRedis(), Vault())
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider.respond)) as http:
        client = OpenAISignInClient(OpenAISignInConfig(CLIENT_ID, REDIRECT), transactions, http)
        yield client, provider


async def start(client, provider):
    handle, location = await client.begin()
    params = {key: values[0] for key, values in parse_qs(urlsplit(location).query).items()}
    provider.nonce = params["nonce"]
    callback = [("state", params["state"]), ("code", "single-use-code")]
    return handle, params, callback


def token_calls(provider):
    return [call for call in provider.calls if str(call.url) == ENDPOINTS["token_endpoint"]]


async def test_public_identity_flow_pkce_and_encrypted_temporary_state(flow):
    client, provider = flow
    handle, params, callback = await start(client, provider)
    redis = client.transactions.redis
    key = client.transactions._key(handle)
    raw = redis.values[key]
    stored = client.transactions.vault.decrypt(raw)
    assert handle not in key
    assert stored["verifier"] not in raw and params["nonce"] not in raw
    assert stored["expires_at"] <= time.time() + TRANSACTION_TTL
    assert params["scope"] == "openid profile email"
    assert params["code_challenge_method"] == "S256"
    expected_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(stored["verifier"].encode()).digest(),
    ).rstrip(b"=").decode()
    assert params["code_challenge"] == expected_challenge
    identity = await client.finish(handle, callback)
    assert (identity.issuer, identity.client_id, identity.subject) == (
        ISSUER, CLIENT_ID, "openai-subject-a",
    )
    assert identity.email_verified is False  # Email is metadata, not account ownership.
    request = token_calls(provider)[0]
    form = parse_qs(request.content.decode())
    assert form["code_verifier"] == [stored["verifier"]]
    assert form["redirect_uri"] == [REDIRECT]
    assert form["client_id"] == [CLIENT_ID]
    assert "authorization" not in request.headers and "client_secret" not in form
    assert not redis.values
    assert "id_token" not in asdict(identity)


async def test_fresh_values_and_browser_binding(flow):
    client, provider = flow
    handle_a, params_a, callback_a = await start(client, provider)
    handle_b, params_b, _ = await start(client, provider)
    assert handle_a != handle_b
    for field in ("state", "nonce", "code_challenge"):
        assert params_a[field] != params_b[field]
    with pytest.raises(OpenAISignInError):
        await client.finish(handle_b, callback_a)
    assert not token_calls(provider)
    provider.nonce = params_a["nonce"]
    assert (await client.finish(handle_a, callback_a)).subject == "openai-subject-a"


async def test_simultaneous_callbacks_across_workers_redeem_once(flow):
    client, provider = flow
    handle, _, callback = await start(client, provider)
    second_worker = OpenAISignInClient(client.config, client.transactions, client.http)
    results = await asyncio.gather(
        client.finish(handle, callback), second_worker.finish(handle, callback),
        return_exceptions=True,
    )
    assert sum(isinstance(result, OpenAISignInError) for result in results) == 1
    assert len(token_calls(provider)) == 1


@pytest.mark.parametrize("failure", [
    "missing_cookie", "wrong_state", "expired", "error", "missing_code",
    "duplicate_state", "wrong_issuer", "wrong_client", "changed_registration",
])
async def test_bad_callbacks_never_redeem_a_code(flow, failure):
    client, provider = flow
    handle, _, callback = await start(client, provider)
    if failure == "missing_cookie":
        handle = ""
    elif failure == "wrong_state":
        callback[0] = ("state", "wrong-state")
    elif failure == "expired":
        client.transactions.redis.expiry[client.transactions._key(handle)] = 0
    elif failure == "error":
        callback.append(("error", "access_denied"))
    elif failure == "missing_code":
        callback.pop()
    elif failure == "duplicate_state":
        callback.append(callback[0])
    elif failure == "wrong_issuer":
        callback.append(("iss", "https://attacker.test"))
    elif failure == "wrong_client":
        callback.append(("client_id", "oaiapp_another_client"))
    elif failure == "changed_registration":
        client.config = OpenAISignInConfig("oaiapp_replacement_client", REDIRECT)
    with pytest.raises(OpenAISignInError):
        await client.finish(handle, callback)
    assert not token_calls(provider)


@pytest.mark.parametrize("changes,missing", [
    ({"iss": "https://attacker.test"}, []),
    ({"aud": "oaiapp_another_client"}, []),
    ({"aud": [CLIENT_ID, "another-audience"]}, []),
    ({"azp": "another-client"}, []),
    ({"exp": 1}, []),
    ({"iat": int(time.time()) + 600}, []),
    ({"nonce": "wrong-nonce"}, []),
    ({"nonce": 1}, []),
    ({"sub": " "}, []),
    ({"sub": 7}, []),
    ({"sid": ""}, []),
    ({"email_verified": "true"}, []),
    ({}, ["exp"]),
    ({}, ["iat"]),
    ({}, ["sub"]),
    ({}, ["nonce"]),
])
async def test_rejects_invalid_signed_identity_claims(flow, changes, missing):
    client, provider = flow
    handle, _, callback = await start(client, provider)
    provider.claim_changes, provider.missing_claims = changes, missing
    with pytest.raises(OpenAISignInError):
        await client.finish(handle, callback)
    with pytest.raises(OpenAISignInError):
        await client.finish(handle, callback)
    assert len(token_calls(provider)) == 1


@pytest.mark.parametrize("kind", ["wrong_key", "wrong_algorithm", "missing_id_token", "failure"])
async def test_token_exchange_and_signature_fail_closed(flow, kind):
    client, provider = flow
    handle, _, callback = await start(client, provider)
    if kind == "wrong_key":
        attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        provider.token_override = jwt.encode(
            {"sub": "attacker"}, attacker, algorithm="RS256", headers={"kid": provider.kid},
        )
    elif kind == "wrong_algorithm":
        provider.token_override = jwt.encode(
            {"sub": "attacker"}, "a" * 32, algorithm="HS256", headers={"kid": provider.kid},
        )
    elif kind == "missing_id_token":
        provider.token_payload = {"access_token": "not-an-id-token"}
    else:
        provider.token_status = 401
        provider.token_payload = {"error_description": "secret-from-provider"}
    with pytest.raises(OpenAISignInError) as error:
        await client.finish(handle, callback)
    assert "secret-from-provider" not in str(error.value)


async def test_confidential_client_secret_only_in_basic_header(flow):
    client, provider = flow
    secret = "s:e c+r/et"
    client.config = OpenAISignInConfig(CLIENT_ID, REDIRECT, "client_secret_basic", secret)
    handle, params, callback = await start(client, provider)
    await client.finish(handle, callback)
    request = token_calls(provider)[0]
    decoded = base64.b64decode(request.headers["authorization"].split(" ")[1]).decode()
    assert decoded == CLIENT_ID + ":s%3Ae+c%2Br%2Fet"
    assert "client_secret" not in parse_qs(request.content.decode())
    assert secret not in request.content.decode() and secret not in str(params)
    assert secret not in repr(client.config)


@pytest.mark.parametrize("changes", [
    {"issuer": "https://attacker.test"},
    {"token_endpoint": "https://attacker.test/token"},
    {"jwks_uri": "http://127.0.0.1/keys"},
    {"code_challenge_methods_supported": []},
    {"id_token_signing_alg_values_supported": ["HS256"]},
    {"token_endpoint_auth_methods_supported": ["client_secret_post"]},
])
async def test_discovery_pins_trust_and_capabilities(flow, changes):
    client, provider = flow
    provider.metadata_changes = changes
    with pytest.raises(OpenAISignInError):
        await client.begin()
    assert not client.transactions.redis.values
    assert len(provider.calls) == 1


async def test_refreshes_rotated_signing_key(flow):
    client, provider = flow
    handle, _, callback = await start(client, provider)
    await client.finish(handle, callback)
    provider.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    provider.kid = "rotated-key"
    handle, _, callback = await start(client, provider)
    assert (await client.finish(handle, callback)).subject == "openai-subject-a"
    assert sum(str(call.url) == ENDPOINTS["jwks_uri"] for call in provider.calls) == 2


@pytest.mark.parametrize("client_id,redirect,method,secret", [
    ("oaiapp_example", REDIRECT, "none", ""),
    ("oaiapp_EHBV7pzdMtehZ7j6Ypgyje-F", REDIRECT, "none", ""),
    (CLIENT_ID, "http://aura.test/auth/openai/callback", "none", ""),
    (CLIENT_ID, REDIRECT + "?return=somewhere", "none", ""),
    (CLIENT_ID, REDIRECT, "client_secret_basic", ""),
    (CLIENT_ID, REDIRECT, "none", "unexpected-secret"),
    (CLIENT_ID, REDIRECT, "client_secret_post", "secret"),
])
def test_invalid_registration_cannot_start(client_id, redirect, method, secret):
    with pytest.raises(OpenAISignInError):
        OpenAISignInConfig(client_id, redirect, method, secret)


@pytest.mark.parametrize("failure", [None, "bad_nonce", "account_policy", "redis"])
async def test_browser_routes_clear_cookie_and_keep_credentials_server_side(flow, failure):
    client, provider = flow
    seen = []

    async def complete(request, identity):
        seen.append(identity)
        if failure == "account_policy":
            raise RuntimeError("internal-policy-detail")
        response = RedirectResponse("https://aura.test/app", status_code=302)
        response.set_cookie("__Host-test-session", "opaque-local-session", secure=True, httponly=True)
        return response

    app = FastAPI()
    app.include_router(openai_signin_router(client, complete))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://aura.test",
    ) as browser:
        response = await browser.get("/auth/openai")
        assert response.status_code == 302
        assert response.headers["cache-control"] == "no-store"
        cookie = response.headers["set-cookie"]
        assert all(part in cookie for part in ("Secure", "HttpOnly", "SameSite=lax", "Path=/"))
        assert "Domain=" not in cookie
        params = parse_qs(urlsplit(response.headers["location"]).query)
        provider.nonce = "wrong" if failure == "bad_nonce" else params["nonce"][0]
        if failure == "redis":
            async def unavailable(handle):
                raise RuntimeError("redis-secret-internal-details")
            client.transactions.consume = unavailable
        response = await browser.get(CALLBACK_PATH, params={
            "state": params["state"][0], "code": "single-use-code",
        })
        assert response.status_code == (302 if failure is None else 400 if failure == "bad_nonce" else 503)
        assert "Max-Age=0" in " ".join(response.headers.get_list("set-cookie"))
        assert COOKIE_NAME not in browser.cookies
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cache-control"] == "no-store"
        assert not any(secret in response.text for secret in (
            "single-use-code", "internal-policy-detail", "redis-secret-internal-details",
        ))
        assert len(seen) == (0 if failure in {"bad_nonce", "redis"} else 1)
        assert "test@example.test" not in str(response.headers)
        if failure is None:
            assert browser.cookies["__Host-test-session"] == "opaque-local-session"


async def test_starting_again_invalidates_previous_browser_transaction(flow):
    client, provider = flow

    async def complete(request, identity):
        return RedirectResponse("/app")

    app = FastAPI()
    app.include_router(openai_signin_router(client, complete))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://aura.test",
    ) as browser:
        first = await browser.get("/auth/openai")
        previous = browser.cookies[COOKIE_NAME]
        first_params = parse_qs(urlsplit(first.headers["location"]).query)
        await browser.get("/auth/openai")
        assert len(client.transactions.redis.values) == 1
        with pytest.raises(OpenAISignInError):
            await client.finish(previous, [("state", first_params["state"][0]), ("code", "old")])
        assert not token_calls(provider)
