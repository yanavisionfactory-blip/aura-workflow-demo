from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session

from .config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(Session, "after_begin")
def restore_tenant_context(session, transaction, connection) -> None:
    workspace_id = session.info.get("aura_workspace_id")
    if workspace_id and connection.dialect.name == "postgresql":
        connection.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                           {"tenant_id": workspace_id})


async def session_dependency() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def set_tenant_context(session: AsyncSession, workspace_id: str) -> None:
    session.info["aura_workspace_id"] = workspace_id
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": workspace_id},
    )
