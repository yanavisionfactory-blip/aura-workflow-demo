import json
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"
    public_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"
    database_url: str = "postgresql+psycopg://aura:aura@postgres:5432/aura"
    redis_url: str = "redis://redis:6379/0"
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4-mini"
    credential_encryption_key: str = Field(
        description="URL-safe Fernet key; generate with Fernet.generate_key().decode()"
    )
    credential_encryption_previous_keys: str = ""
    session_signing_key: str = Field(min_length=32)
    google_client_id: str = ""
    google_client_secret: str = ""
    airtable_client_id: str = ""
    airtable_client_secret: str = ""
    slack_client_id: str = ""
    slack_client_secret: str = ""
    notion_client_id: str = ""
    notion_client_secret: str = ""
    tiktok_client_id: str = ""
    tiktok_client_secret: str = ""
    mailchimp_client_id: str = ""
    mailchimp_client_secret: str = ""
    canva_client_id: str = ""
    canva_client_secret: str = ""
    hubspot_client_id: str = ""
    hubspot_client_secret: str = ""
    atlassian_client_id: str = ""
    atlassian_client_secret: str = ""
    oauth_callback_overrides: str = ""
    browser_connector_url: str = ""
    # Clerk is the production identity provider. The PEM key avoids a network
    # request on every API call; JWKS is supported for key rotation.
    clerk_jwt_key: str = ""
    clerk_jwks_url: str = ""
    clerk_issuer: str = ""
    clerk_authorized_parties: str = ""
    allow_legacy_workspace_tokens: bool = False
    run_rate_limit_per_minute: int = 60
    # Optional managed connector control plane. When configured, AURA delegates
    # OAuth storage and refresh to Nango and keeps only connection references.
    nango_api_key: str = ""
    nango_base_url: str = "https://api.nango.dev"
    nango_integration_map: str = "{}"

    @property
    def clerk_enabled(self) -> bool:
        return bool(self.clerk_jwt_key or self.clerk_jwks_url)

    @property
    def clerk_parties(self) -> set[str]:
        return {
            item.strip().rstrip("/")
            for item in self.clerk_authorized_parties.split(",")
            if item.strip()
        }

    @property
    def credential_keyring(self) -> list[str]:
        return [
            self.credential_encryption_key,
            *[
                key.strip()
                for key in self.credential_encryption_previous_keys.split(",")
                if key.strip()
            ],
        ]


    @property
    def managed_integrations(self) -> dict[str, str]:
        try:
            value = json.loads(self.nango_integration_map or "{}")
        except json.JSONDecodeError:
            return {}
        if not isinstance(value, dict):
            return {}
        return {
            str(provider).strip().lower(): str(integration).strip()
            for provider, integration in value.items()
            if str(provider).strip() and str(integration).strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
