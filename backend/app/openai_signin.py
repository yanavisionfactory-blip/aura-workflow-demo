"""OpenAI identity sign-in primitives; deliberately not mounted in the live app.

This is identity-only OIDC, not permission to use a ChatGPT subscription. A route
adapter must resolve/link the verified identity under AURA's account policy and
issue an AURA session. No default adapter can bypass the existing Clerk login.
"""

import asyncio
import base64
import hashlib
import hmac
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Literal, Protocol
from urllib.parse import quote_plus, urlencode, urlsplit

import httpx
import jwt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

ISSUER = "https://auth.openai.com"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
ENDPOINTS = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/api/accounts/authorize",
    "token_endpoint": f"{ISSUER}/api/accounts/oauth/token",
    "jwks_uri": f"{ISSUER}/.well-known/jwks.json",
}
CALLBACK_PATH = "/auth/openai/callback"
COOKIE_NAME = "__Host-aura_openai_transaction"
TRANSACTION_TTL = 600
CACHE_TTL = 300


class OpenAISignInError(ValueError):
    """Safe, fixed-message errors: never attach a provider body or credential."""


@dataclass(frozen=True)
class OpenAISignInConfig:
    client_id: str
    redirect_uri: str
    auth_method: Literal["none", "client_secret_basic"] = "none"
    client_secret: str = field(default="", repr=False)

    def __post_init__(self):
        if (
            not re.fullmatch(r"oaiapp_[A-Za-z0-9_-]{8,200}", self.client_id)
            or self.client_id == "oaiapp_EHBV7pzdMtehZ7j6Ypgyje-F"
        ):
            raise OpenAISignInError("An OpenAI-issued AURA client ID is required.")
        parsed = urlsplit(self.redirect_uri)
        if (
            parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path != CALLBACK_PATH
        ):
            raise OpenAISignInError("An exact registered HTTPS callback is required.")
        if self.auth_method not in {"none", "client_secret_basic"}:
            raise OpenAISignInError("Unsupported registered client authentication method.")
        if (self.auth_method == "client_secret_basic") != bool(self.client_secret):
            raise OpenAISignInError("Credentials must match the registered client type.")


class TransactionRedis(Protocol):
    async def set(self, name, value, *, ex, nx): ...
    async def getdel(self, name): ...


class TransactionVault(Protocol):
    def encrypt(self, value: dict) -> str: ...
    def decrypt(self, value: str) -> dict: ...


@dataclass(frozen=True, repr=False)
class SignInTransaction:
    state: str
    verifier: str
    nonce: str
    client_id: str
    redirect_uri: str
    expires_at: int


class RedisSignInTransactions:
    """Encrypted temporary state, shared across API instances, consumed once."""

    def __init__(self, redis: TransactionRedis, vault: TransactionVault):
        self.redis = redis
        self.vault = vault

    @staticmethod
    def _key(browser_handle: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", browser_handle):
            raise OpenAISignInError("Sign-in could not be verified. Please start again.")
        return "aura:openai-signin:" + hashlib.sha256(browser_handle.encode()).hexdigest()

    async def create(self, config: OpenAISignInConfig) -> tuple[str, SignInTransaction]:
        browser_handle = secrets.token_urlsafe(32)
        transaction = SignInTransaction(
            state=secrets.token_urlsafe(32), verifier=secrets.token_urlsafe(64),
            nonce=secrets.token_urlsafe(32), client_id=config.client_id,
            redirect_uri=config.redirect_uri, expires_at=int(time.time()) + TRANSACTION_TTL,
        )
        stored = await self.redis.set(
            self._key(browser_handle), self.vault.encrypt(asdict(transaction)),
            ex=TRANSACTION_TTL, nx=True,
        )
        if not stored:
            raise OpenAISignInError("Sign-in could not be started. Please retry.")
        return browser_handle, transaction

    async def consume(self, browser_handle: str) -> SignInTransaction:
        # Redis GETDEL is atomic across workers. Never replace it with GET + DEL.
        raw = await self.redis.getdel(self._key(browser_handle))
        if not raw:
            raise OpenAISignInError("Sign-in expired or was already used. Please start again.")
        try:
            if isinstance(raw, bytes):
                raw = raw.decode()
            result = SignInTransaction(**self.vault.decrypt(raw))
            if result.expires_at <= time.time():
                raise ValueError("expired")
            if not all(isinstance(value, str) and value for value in (
                result.state, result.verifier, result.nonce,
                result.client_id, result.redirect_uri,
            )):
                raise ValueError("invalid transaction")
            return result
        except (ValueError, TypeError, RuntimeError):
            raise OpenAISignInError("Sign-in could not be verified. Please start again.") from None


@dataclass(frozen=True, repr=False)
class OpenAIIdentity:
    issuer: str
    client_id: str
    subject: str
    email: str | None
    email_verified: bool
    name: str | None
    picture: str | None
    sid: str | None


class OpenAISignInClient:
    def __init__(
        self, config: OpenAISignInConfig, transactions: RedisSignInTransactions,
        http: httpx.AsyncClient,
    ):
        # Caller owns the HTTP client's lifespan. Never enable body/header debug logging.
        self.config, self.transactions, self.http = config, transactions, http
        self._metadata: dict = {}
        self._metadata_at = 0.0
        self._keys: list[dict] = []
        self._keys_at = 0.0
        self._unknown_key_refresh_at = 0.0
        self._metadata_lock = asyncio.Lock()
        self._keys_lock = asyncio.Lock()

    async def _json(self, method: str, url: str, **kwargs) -> dict:
        try:
            response = await self.http.request(
                method, url, timeout=10, follow_redirects=False, **kwargs,
            )
            if response.status_code != 200 or len(response.content) > 262_144:
                raise ValueError("invalid provider response")
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("invalid provider response")
            return result
        except (httpx.HTTPError, ValueError):
            raise OpenAISignInError("OpenAI sign-in is unavailable. Please start again.") from None

    async def discovery(self) -> dict:
        async with self._metadata_lock:
            if self._metadata and time.monotonic() - self._metadata_at < CACHE_TTL:
                return self._metadata
            metadata = await self._json("GET", DISCOVERY_URL)
            # Pin the published production trust boundary; never follow discovered
            # endpoints to a different host or an arbitrary URL supplied by a caller.
            if any(metadata.get(key) != value for key, value in ENDPOINTS.items()):
                raise OpenAISignInError("OpenAI identity configuration could not be verified.")
            required = {
                "response_types_supported": "code",
                "code_challenge_methods_supported": "S256",
                "id_token_signing_alg_values_supported": "RS256",
                "token_endpoint_auth_methods_supported": self.config.auth_method,
            }
            if any(
                not isinstance(metadata.get(key), list) or value not in metadata[key]
                for key, value in required.items()
            ):
                raise OpenAISignInError("OpenAI identity configuration is incompatible.")
            self._metadata, self._metadata_at = metadata, time.monotonic()
            return metadata

    async def begin(self) -> tuple[str, str]:
        metadata = await self.discovery()
        handle, transaction = await self.transactions.create(self.config)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(transaction.verifier.encode()).digest(),
        ).rstrip(b"=").decode()
        query = urlencode({
            "client_id": self.config.client_id, "redirect_uri": transaction.redirect_uri,
            "response_type": "code", "scope": "openid profile email",
            "state": transaction.state, "nonce": transaction.nonce,
            "code_challenge": challenge, "code_challenge_method": "S256",
        })
        return handle, metadata["authorization_endpoint"] + "?" + query

    async def finish(self, handle: str, parameters: list[tuple[str, str]]) -> OpenAIIdentity:
        transaction = await self.transactions.consume(handle)
        params = dict(parameters)
        if (
            len(params) != len(parameters)
            or not hmac.compare_digest(params.get("state", "").encode(), transaction.state.encode())
            or transaction.client_id != self.config.client_id
            or transaction.redirect_uri != self.config.redirect_uri
            or params.get("iss", ISSUER) != ISSUER
            or params.get("client_id", self.config.client_id) != self.config.client_id
        ):
            raise OpenAISignInError("Sign-in could not be verified. Please start again.")
        if "error" in params:
            raise OpenAISignInError("OpenAI sign-in was not completed. Please start again.")
        code = params.get("code", "")
        if not code or len(code) > 4096:
            raise OpenAISignInError("OpenAI did not return a valid sign-in code.")
        metadata = await self.discovery()
        data = {
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": transaction.redirect_uri, "code_verifier": transaction.verifier,
        }
        headers = {"accept": "application/json"}
        if self.config.auth_method == "none":
            data["client_id"] = self.config.client_id
        else:
            encoded = ":".join(quote_plus(value, safe="") for value in (
                self.config.client_id, self.config.client_secret,
            ))
            headers["authorization"] = "Basic " + base64.b64encode(encoded.encode()).decode()
        tokens = await self._json("POST", metadata["token_endpoint"], data=data, headers=headers)
        token = tokens.get("id_token")
        if not isinstance(token, str) or not token or len(token) > 65_536:
            raise OpenAISignInError("OpenAI did not return a valid identity token.")
        # Access/refresh tokens are not required, persisted, or exposed by this flow.
        return await self._verify_identity(token, transaction.nonce, metadata["jwks_uri"])

    async def _signing_key(self, kid: str, jwks_uri: str):
        async with self._keys_lock:
            age = time.monotonic() - self._keys_at
            matching = [item for item in self._keys if item.get("kid") == kid]
            # Refresh unfamiliar kids, with a short cooldown to bound invalid-token
            # traffic. No key URL from a JWT header is ever fetched.
            unknown = not matching and time.monotonic() - self._unknown_key_refresh_at >= 5
            if not self._keys or age >= CACHE_TTL or unknown:
                if self._keys and unknown:
                    self._unknown_key_refresh_at = time.monotonic()
                body = await self._json("GET", jwks_uri)
                keys = body.get("keys")
                if not isinstance(keys, list) or not keys or len(keys) > 100:
                    raise OpenAISignInError("OpenAI signing keys could not be verified.")
                self._keys = [key for key in keys if isinstance(key, dict)]
                self._keys_at = time.monotonic()
                matching = [item for item in self._keys if item.get("kid") == kid]
            if len(matching) != 1:
                raise OpenAISignInError("OpenAI identity could not be verified.")
            key = matching[0]
            if (
                key.get("kty") != "RSA" or key.get("use", "sig") != "sig"
                or key.get("alg", "RS256") != "RS256"
                or "verify" not in key.get("key_ops", ["verify"])
            ):
                raise OpenAISignInError("OpenAI identity could not be verified.")
            return jwt.PyJWK.from_dict(key, algorithm="RS256").key

    async def _verify_identity(self, token: str, nonce: str, jwks_uri: str) -> OpenAIIdentity:
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
                raise ValueError("invalid signing header")
            key = await self._signing_key(kid, jwks_uri)
            claims = jwt.decode(
                token, key, algorithms=["RS256"], issuer=ISSUER,
                audience=self.config.client_id, leeway=5,
                options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]},
            )
            if (
                not isinstance(claims["sub"], str) or not claims["sub"].strip()
                or not isinstance(claims["nonce"], str)
                or not hmac.compare_digest(claims["nonce"].encode(), nonce.encode())
                or any(type(claims[name]) is not int for name in ("iat", "exp"))
                or claims["exp"] <= claims["iat"]
                or claims.get("azp", self.config.client_id) != self.config.client_id
                or (isinstance(claims["aud"], list) and len(claims["aud"]) > 1
                    and claims.get("azp") != self.config.client_id)
            ):
                raise ValueError("invalid identity claims")
            for name in ("email", "name", "picture", "sid"):
                if name in claims and (not isinstance(claims[name], str) or not claims[name].strip()):
                    raise ValueError("invalid optional identity claim")
            if "email_verified" in claims and not isinstance(claims["email_verified"], bool):
                raise ValueError("invalid email verification claim")
            return OpenAIIdentity(
                issuer=ISSUER, client_id=self.config.client_id, subject=claims["sub"],
                email=claims.get("email"), email_verified=claims.get("email_verified", False),
                name=claims.get("name"), picture=claims.get("picture"), sid=claims.get("sid"),
            )
        except (jwt.PyJWTError, KeyError, TypeError, ValueError):
            raise OpenAISignInError("OpenAI identity could not be verified.") from None


def openai_signin_router(
    client: OpenAISignInClient,
    complete_signin: Callable[[Request, OpenAIIdentity], Awaitable[Response]],
) -> APIRouter:
    """Requires an explicit account/session adapter; never auto-link by email.

    The adapter must resolve (issuer, client_id, subject), enforce account and
    enterprise policy, confirm new links using an existing authenticated account,
    and issue a first-party session. It must not return identity claims in URLs.
    Mount only after the approved client and the Clerk/session adapter are tested.
    """
    router = APIRouter()

    def private(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def clear_transaction(response: Response) -> Response:
        response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax")
        return private(response)

    @router.get("/auth/openai", include_in_schema=False)
    async def start(request: Request):
        try:
            previous = request.cookies.get(COOKIE_NAME)
            if previous:
                try:
                    await client.transactions.consume(previous)
                except OpenAISignInError:
                    pass
            handle, location = await client.begin()
        except Exception:
            # Redis/HTTP/adapter exceptions must not leak transaction or token data.
            return clear_transaction(JSONResponse(
                {"detail": "ChatGPT sign-in is unavailable. Please try again."}, status_code=503,
            ))
        response = RedirectResponse(location, status_code=302)
        response.set_cookie(
            COOKIE_NAME, handle, max_age=TRANSACTION_TTL, path="/", secure=True,
            httponly=True, samesite="lax",
        )
        return private(response)

    @router.get(CALLBACK_PATH, include_in_schema=False)
    async def callback(request: Request):
        try:
            identity = await client.finish(
                request.cookies.get(COOKIE_NAME, ""), list(request.query_params.multi_items()),
            )
            response = await complete_signin(request, identity)
        except OpenAISignInError:
            response = JSONResponse(
                {"detail": "ChatGPT sign-in could not be verified. Please start again."},
                status_code=400,
            )
        except Exception:
            response = JSONResponse(
                {"detail": "ChatGPT sign-in is unavailable. Please start again."}, status_code=503,
            )
        return clear_transaction(response)

    return router
