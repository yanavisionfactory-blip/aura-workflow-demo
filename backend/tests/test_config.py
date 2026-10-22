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


def test_render_database_urls_use_the_installed_async_psycopg_driver():
    from sqlalchemy.engine import make_url

    for scheme in ("postgres", "postgresql", "PostgreSQL"):
        settings = Settings(
            _env_file=None,
            database_url=scheme + "://user:p%40ss@internal-host:5432/aura?sslmode=require",
            credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            session_signing_key="test-session-signing-key-000000000",
        )
        url = make_url(settings.database_url)
        assert url.drivername == "postgresql+psycopg"
        assert url.password == "p@ss"
        assert url.host == "internal-host"
        assert url.database == "aura"
        assert url.query["sslmode"] == "require"
        assert url.get_dialect().get_async_dialect_cls(url).is_async


def test_explicit_database_drivers_remain_unchanged():
    for value in (
        "postgresql+psycopg://user:password@internal-host/aura",
        "sqlite+aiosqlite:///:memory:",
    ):
        settings = Settings(
            _env_file=None,
            database_url=value,
            credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            session_signing_key="test-session-signing-key-000000000",
        )
        assert settings.database_url == value
