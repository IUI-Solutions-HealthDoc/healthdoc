"""Async SQLAlchemy session + declarative base. Modules define models on Base."""
import ssl
from collections.abc import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.common.config import get_settings

# Constraint/index naming — docs/schema-conventions.md §3. Do not override per-table.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _connect_args(ca_file: str | None) -> dict:
    """TLS to the database when a CA is configured (the control-room server).

    A default context verifies the chain AND the host name, i.e. libpq's
    verify-full. "require" alone would encrypt to whoever answers on the
    private address, which is the attack TLS is there to stop.
    """
    if not ca_file:
        return {}
    return {"ssl": ssl.create_default_context(cafile=ca_file)}


engine = create_async_engine(
    get_settings().database_url, pool_pre_ping=True,
    connect_args=_connect_args(get_settings().database_ssl_ca_file),
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a session, commits on success, rolls back on error."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
