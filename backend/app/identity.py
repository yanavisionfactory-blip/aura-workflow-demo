from functools import lru_cache

import jwt
from jwt import PyJWKClient

from .config import get_settings


class IdentityError(ValueError):
    pass


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    settings = get_settings()
    if not settings.clerk_jwks_url:
        raise IdentityError("CLERK_JWKS_URL is not configured")
    return PyJWKClient(settings.clerk_jwks_url, cache_keys=True)


def verify_clerk_session(token: str) -> dict:
    """Verify a Clerk session JWT and its browser origin."""
    settings = get_settings()
    if not settings.clerk_enabled:
        raise IdentityError("Clerk is not configured")

    try:
        if settings.clerk_jwt_key:
            key = settings.clerk_jwt_key.replace("\\n", "\n")
        else:
            key = _jwks_client().get_signing_key_from_jwt(token).key
        options = {"require": ["exp", "sub"], "verify_aud": False}
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer or None,
            options=options,
        )
    except jwt.PyJWTError as exc:
        raise IdentityError("Invalid Clerk session") from exc

    if claims.get("sts") == "pending":
        raise IdentityError("Organization membership is pending")
    authorized_parties = settings.clerk_parties
    azp = str(claims.get("azp", "")).rstrip("/")
    if authorized_parties and (not azp or azp not in authorized_parties):
        raise IdentityError("Session was issued to an unauthorized party")
    return claims


def organization_claims(claims: dict) -> tuple[str | None, str]:
    """Support both Clerk's compact and legacy organization claim formats."""
    compact = claims.get("o") if isinstance(claims.get("o"), dict) else {}
    organization_id = claims.get("org_id") or compact.get("id")
    raw_role = claims.get("org_role") or compact.get("rol") or "member"
    role_name = str(raw_role).removeprefix("org:")
    role = "admin" if role_name in {"admin", "owner"} else "member"
    return organization_id, role
