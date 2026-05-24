"""Async SQLAlchemy engine and session factory."""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from paper2beamer.db.models import Base
from paper2beamer.config import settings

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.database_url, echo=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def init_db():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
