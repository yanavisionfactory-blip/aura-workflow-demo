import base64

import pytest

from app.installation_runtime import (
    ConnectorInstallationError,
    normalized_credentials,
)


def test_bearer_credentials_are_normalized():
    result = normalized_credentials("bearer", {"access_token": "secret"})
    assert result == {
        "access_token": "secret",
        "header": "Authorization",
        "prefix": "Bearer",
    }


def test_api_key_supports_custom_header_without_exposing_provider_logic():
    result = normalized_credentials(
        "api_key",
        {"api_key": "secret", "header": "X-API-Key", "prefix": ""},
    )
    assert result["header"] == "X-API-Key"
    assert result["prefix"] == ""


def test_basic_credentials_are_encoded_for_standard_authorization():
    result = normalized_credentials(
        "basic", {"username": "yana", "password": "secret"}
    )
    assert result["prefix"] == "Basic"
    assert base64.b64decode(result["access_token"]).decode() == "yana:secret"


def test_oauth_requires_platform_client_id():
    with pytest.raises(ConnectorInstallationError, match="client_id"):
        normalized_credentials("oauth2", {"client_secret": "secret"})


def test_no_auth_stores_no_credentials():
    assert normalized_credentials("none", {}) == {}
