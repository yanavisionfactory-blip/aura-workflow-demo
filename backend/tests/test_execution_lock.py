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
