from app.config import Settings
from app.providers import PROVIDERS, oauth_callback_url, oauth_authorization_url, idempotency_key


def _settings() -> Settings:
    return Settings(
        credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        session_signing_key="x" * 32,
        public_url="https://api.example.com",
        notion_client_id="notion-client",
        notion_client_secret="notion-secret",
    )


def test_notion_uses_shared_callback_and_owner_authorization():
    provider = PROVIDERS["notion"]
    settings = _settings()
    assert oauth_callback_url(settings, provider) == "https://api.example.com/v1/oauth/installation/callback"
    url = oauth_authorization_url(settings, provider, "signed-state")
    assert "owner=user" in url
    assert "client_id=notion-client" in url


def test_idempotency_is_stable_for_argument_order():
    left = idempotency_key("run", 1, "gmail.send", {"to": "a@example.com", "body": "x"})
    right = idempotency_key("run", 1, "gmail.send", {"body": "x", "to": "a@example.com"})
    assert left == right


def test_idempotency_changes_with_step_position():
    left = idempotency_key("run", 1, "gmail.send", {"to": "a@example.com"})
    right = idempotency_key("run", 2, "gmail.send", {"to": "a@example.com"})
    assert left != right
