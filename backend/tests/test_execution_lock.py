import os

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.execution_lock import execution_lock


@pytest.mark.skipif(
    not os.getenv("AURA_TEST_POSTGRES_URL"),
    reason="PostgreSQL integration URL not configured",
)
async def test_duplicate_delivery_lock_and_release_after_exception():
    engine = create_async_engine(os.environ["AURA_TEST_POSTGRES_URL"])
    try:
        with pytest.raises(RuntimeError, match="worker failure"):
            async with execution_lock(engine, "workspace", "run") as first:
                assert first is True
                async with execution_lock(engine, "workspace", "run") as duplicate:
                    assert duplicate is False
                async with execution_lock(
                    engine, "other-workspace", "run"
                ) as independent:
                    assert independent is True
                raise RuntimeError("worker failure")
        async with execution_lock(engine, "workspace", "run") as recovered:
            assert recovered is True
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not os.getenv("AURA_TEST_POSTGRES_URL"),
    reason="PostgreSQL integration URL not configured",
)
async def test_tenant_context_survives_checkpoint_commits():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.db import set_tenant_context

    engine = create_async_engine(os.environ["AURA_TEST_POSTGRES_URL"])
    try:
        async with async_sessionmaker(engine)() as session:
            await set_tenant_context(session, "tenant-checkpoint")
            await session.commit()
            assert (
                await session.scalar(
                    text("SELECT current_setting('app.tenant_id', true)")
                )
                == "tenant-checkpoint"
            )
            await session.commit()
            assert (
                await session.scalar(
                    text("SELECT current_setting('app.tenant_id', true)")
                )
                == "tenant-checkpoint"
            )
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not os.getenv("AURA_TEST_POSTGRES_URL"),
    reason="PostgreSQL integration URL not configured",
)
async def test_memory_table_migration_has_forced_tenant_policy(monkeypatch):
    from sqlalchemy import text
    from app import migrations

    engine = create_async_engine(os.environ["AURA_TEST_POSTGRES_URL"])
    monkeypatch.setattr(migrations, "engine", engine)
    try:
        await migrations.migrate_database()
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'workflow_memories'"
                    )
                )
                is True
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_policies WHERE tablename = 'workflow_memories' AND policyname = 'tenant_isolation'"
                    )
                )
                == 1
            )
    finally:
        await engine.dispose()
