"""FastAPI dependency injection."""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# These will be set during app lifespan startup
_session_factory: async_sessionmaker[AsyncSession] | None = None


def set_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    global _session_factory
    _session_factory = factory


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory for direct use (not a context manager)."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized")
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a transactional async DB session."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized")
    async with _session_factory() as session:
        async with session.begin():
            yield session
