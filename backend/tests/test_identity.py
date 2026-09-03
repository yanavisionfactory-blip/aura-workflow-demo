from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import get_settings
from app.identity import IdentityError, organization_claims, verify_clerk_session


def _keys() -> tuple[str, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes_raw() if hasattr(private, "private_bytes_raw") else None
    from cryptography.hazmat.primitives import serialization

    if private_pem is None:
        private_pem = private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem.decode(), public_pem.decode()


def test_verify_clerk_session_and_compact_organization(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key, public_key = _keys()
    monkeypatch.setenv("CLERK_JWT_KEY", public_key)
    monkeypatch.setenv("CLERK_ISSUER", "https://clerk.example")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "https://app.example")
    get_settings.cache_clear()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "user_123",
            "iss": "https://clerk.example",
            "azp": "https://app.example",
            "nbf": now - timedelta(seconds=1),
            "exp": now + timedelta(minutes=5),
            "o": {"id": "org_123", "rol": "admin"},
        },
        private_key,
        algorithm="RS256",
    )
    claims = verify_clerk_session(token)
    assert claims["sub"] == "user_123"
    assert organization_claims(claims) == ("org_123", "admin")
    get_settings.cache_clear()


def test_rejects_wrong_authorized_party(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key, public_key = _keys()
    monkeypatch.setenv("CLERK_JWT_KEY", public_key)
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "https://app.example")
    get_settings.cache_clear()
    token = jwt.encode(
        {
            "sub": "user_123",
            "azp": "https://attacker.example",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )
    with pytest.raises(IdentityError, match="unauthorized party"):
        verify_clerk_session(token)
    get_settings.cache_clear()
