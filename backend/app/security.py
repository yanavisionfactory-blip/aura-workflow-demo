import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .config import get_settings


class CredentialVault:
    def __init__(self) -> None:
        self._fernets = [
            Fernet(key.encode()) for key in get_settings().credential_keyring
        ]
        self._fernet = self._fernets[0]
        self._keyring = MultiFernet(self._fernets)

    def encrypt(self, value: dict) -> str:
        return self._fernet.encrypt(json.dumps(value).encode()).decode()

    def decrypt(self, value: str | None) -> dict:
        if not value:
            return {}
        try:
            return json.loads(self._keyring.decrypt(value.encode()))
        except (InvalidToken, json.JSONDecodeError) as exc:
            raise RuntimeError("Stored tool credentials cannot be decrypted") from exc

    def needs_rotation(self, value: str | None) -> bool:
        if not value:
            return False
        try:
            self._fernet.decrypt(value.encode())
            return False
        except InvalidToken:
            self._keyring.decrypt(value.encode())
            return True

    def rotate(self, value: str) -> str:
        try:
            return self._keyring.rotate(value.encode()).decode()
        except InvalidToken as exc:
            raise RuntimeError("Stored tool credentials cannot be decrypted") from exc


def create_oauth_state(workspace_id: str, provider: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "workspace_id": workspace_id,
            "provider": provider,
            "nonce": secrets.token_urlsafe(16),
            "iat": now,
            "exp": now + timedelta(minutes=10),
        },
        settings.session_signing_key,
        algorithm="HS256",
    )


def decode_oauth_state(token: str) -> dict:
    return jwt.decode(token, get_settings().session_signing_key, algorithms=["HS256"])


def create_tenant_token(workspace_id: str, subject: str, role: str = "owner") -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "typ": "tenant_context",
            "workspace_id": workspace_id,
            "sub": subject,
            "role": role,
            "iat": now,
        },
        get_settings().session_signing_key,
        algorithm="HS256",
    )


def decode_tenant_token(token: str) -> dict:
    claims = jwt.decode(token, get_settings().session_signing_key, algorithms=["HS256"])
    if claims.get("typ") != "tenant_context" or not claims.get("workspace_id"):
        raise jwt.InvalidTokenError("Invalid tenant context")
    return claims


def create_webhook_token(workspace_id: str, subscription_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "typ": "webhook_endpoint",
            "workspace_id": workspace_id,
            "subscription_id": subscription_id,
            "iat": now,
        },
        get_settings().session_signing_key,
        algorithm="HS256",
    )


def decode_webhook_token(token: str) -> dict:
    claims = jwt.decode(token, get_settings().session_signing_key, algorithms=["HS256"])
    if (
        claims.get("typ") != "webhook_endpoint"
        or not claims.get("workspace_id")
        or not claims.get("subscription_id")
    ):
        raise jwt.InvalidTokenError("Invalid webhook endpoint")
    return claims


def webhook_signature(secret: str, timestamp: str, body: bytes) -> str:
    signed = timestamp.encode() + b"." + body
    return "sha256=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def verify_webhook_signature(
    secret: str, timestamp: str, body: bytes, signature: str
) -> bool:
    return hmac.compare_digest(
        webhook_signature(secret, timestamp, body),
        signature,
    )
