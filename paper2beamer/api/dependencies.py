"""FastAPI dependencies."""

from sqlalchemy.ext.asyncio import AsyncSession
from paper2beamer.db.database import get_session_factory


async def get_db() -> AsyncSession:
    factory = get_session_factory()
    async with factory() as session:
        yield session
