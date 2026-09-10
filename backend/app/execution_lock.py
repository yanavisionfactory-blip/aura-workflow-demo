"""Serialize deliveries for a run across workers, including across DB commits."""

from contextlib import asynccontextmanager
import hashlib

from sqlalchemy import text


@asynccontextmanager
async def execution_lock(engine, workspace_id: str, run_id: str):
    # A session advisory lock uses a dedicated connection because the orchestration
    # session commits checkpoints repeatedly. PostgreSQL releases it on disconnect.
    key = int.from_bytes(
        hashlib.sha256(f"{workspace_id}:{run_id}".encode()).digest()[:8],
        "big",
        signed=True,
    )
    async with engine.connect() as connection:
        if connection.dialect.name != "postgresql":
            raise RuntimeError("Durable execution locking requires PostgreSQL")
        acquired = await connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
        )
        await connection.commit()
        try:
            yield bool(acquired)
        finally:
            if acquired:
                try:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                    )
                    await connection.commit()
                except BaseException:
                    await connection.invalidate()
                    raise
