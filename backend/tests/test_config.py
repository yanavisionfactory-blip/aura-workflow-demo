import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings


@pytest.mark.parametrize("prefix", ["postgresql://", "postgres://", "postgresql+psycopg://"])
def test_managed_postgres_urls_select_the_installed_async_driver(prefix):
    suffix = "aura:p%40ss%3Aword@db.internal:5432/aura?sslmode=require&application_name=aura"
    settings = Settings(database_url=prefix + suffix)

    assert settings.database_url == "postgresql+psycopg://" + suffix
    engine = create_async_engine(settings.database_url)
    assert engine.dialect.driver == "psycopg"
    assert engine.dialect.is_async
    assert engine.url.password == "p@ss:word"
    assert engine.url.query["sslmode"] == "require"


@pytest.mark.parametrize("url", ["sqlite+aiosqlite:///:memory:",
                                 "postgresql+psycopg://aura@localhost/aura"])
def test_explicit_database_driver_urls_are_preserved(url):
    assert Settings(database_url=url).database_url == url


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
