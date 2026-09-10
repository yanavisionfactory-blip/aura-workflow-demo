from app.config import Settings


def test_resource_aliases_are_casefolded_and_invalid_values_are_ignored():
    settings = Settings(
        credential_encryption_key=(
            "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
        ),
        session_signing_key="test-session-signing-key-000000000",
        resource_aliases_json=(
            '{"Creator Outreach":"sheet-1","my creators":"sheet-2","":"ignored"}'
        ),
    )

    assert settings.resource_aliases == {
        "creator outreach": "sheet-1",
        "my creators": "sheet-2",
    }
