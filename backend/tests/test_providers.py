from app.config import Settings
from app.providers import PROVIDERS, oauth_callback_url, oauth_authorization_url, idempotency_key


def _settings() -> Settings:
    return Settings(
        credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        session_signing_key="x" * 32,
        public_url="https://api.example.com",
        notion_client_id="notion-client",
        notion_client_secret="notion-secret",
        tiktok_client_id="tiktok-client",
        tiktok_client_secret="tiktok-secret",
        mailchimp_client_id="mailchimp-client",
        mailchimp_client_secret="mailchimp-secret",
        canva_client_id="canva-client",
        canva_client_secret="canva-secret",
        hubspot_client_id="hubspot-client",
        hubspot_client_secret="hubspot-secret",
    )


def test_notion_uses_shared_callback_and_owner_authorization():
    provider = PROVIDERS["notion"]
    settings = _settings()
    assert oauth_callback_url(settings, provider) == "https://api.example.com/v1/oauth/installation/callback"
    url = oauth_authorization_url(settings, provider, "signed-state")
    assert "owner=user" in url
    assert "client_id=notion-client" in url


def test_mailchimp_authorization_omits_scope_when_provider_has_none():
    provider = PROVIDERS["mailchimp"]
    url = oauth_authorization_url(_settings(), provider, "signed-state")
    assert "client_id=mailchimp-client" in url
    assert "scope=" not in url
    assert oauth_callback_url(_settings(), provider) == "https://api.example.com/v1/oauth/installation/callback"


def test_tiktok_uses_shared_callback_and_client_key():
    provider = PROVIDERS["tiktok"]
    settings = _settings()
    assert oauth_callback_url(settings, provider) == "https://api.example.com/v1/oauth/installation/callback"
    url = oauth_authorization_url(settings, provider, "signed-state")
    assert "client_key=tiktok-client" in url
    assert "client_id=" not in url
    assert "scope=user.info.basic%2Cvideo.list%2Cvideo.upload%2Cvideo.publish" in url


def test_canva_uses_shared_callback_and_pkce():
    provider = PROVIDERS["canva"]
    settings = _settings()
    assert oauth_callback_url(settings, provider) == "https://api.example.com/v1/oauth/installation/callback"
    url = oauth_authorization_url(settings, provider, "signed-state")
    assert "client_id=canva-client" in url
    assert "code_challenge_method=S256" in url
    assert "code_challenge=" in url
    assert "profile%3Aread" in url


def test_idempotency_is_stable_for_argument_order():
    left = idempotency_key("run", 1, "gmail.send", {"to": "a@example.com", "body": "x"})
    right = idempotency_key("run", 1, "gmail.send", {"body": "x", "to": "a@example.com"})
    assert left == right


def test_hubspot_uses_managed_oauth_callback_and_crm_scopes():
    provider = PROVIDERS["hubspot"]
    settings = _settings()
    assert oauth_callback_url(settings, provider) == "https://api.example.com/v1/oauth/hubspot/callback"
    url = oauth_authorization_url(settings, provider, "signed-state")
    assert "client_id=hubspot-client" in url
    assert "crm.objects.contacts.read" in url


def test_idempotency_changes_with_step_position():
    left = idempotency_key("run", 1, "gmail.send", {"to": "a@example.com"})
    right = idempotency_key("run", 2, "gmail.send", {"to": "a@example.com"})
    assert left != right
