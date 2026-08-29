import json
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


class CredentialVault:
    def __init__(self) -> None:
        self._fernet = Fernet(get_settings().credential_encryption_key.encode())

    def encrypt(self, value: dict) -> str:
        return self._fernet.encrypt(json.dumps(value).encode()).decode()

    def decrypt(self, value: str | None) -> dict:
        if not value:
            return {}
        try:
            return json.loads(self._fernet.decrypt(value.encode()))
        except (InvalidToken, json.JSONDecodeError) as exc:
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
