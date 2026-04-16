"""Async database engine + session factory.

Engine is created lazily on first use, not at import time.
Falls back to SQLite (aiosqlite) if DATABASE_URL points to
an unreachable Postgres or is not set.
"""

import logging

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

import config

log = logging.getLogger("vyapari.database")


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""
    pass


# ---------------------------------------------------------------------------
# Lazy engine + session factory
# ---------------------------------------------------------------------------

_engine = None
_async_session = None


def _build_engine():
    """Create the async engine from config.DATABASE_URL."""
    url = config.DATABASE_URL
    is_pg = "postgresql" in url
    is_pooler = "pooler.supabase.com" in url or ":6543/" in url

    kwargs = {
        "echo": config.DATABASE_ECHO,
        "pool_pre_ping": True,
    }
    if is_pg:
        kwargs["pool_size"] = config.DATABASE_POOL_SIZE
        kwargs["max_overflow"] = config.DATABASE_MAX_OVERFLOW
    if is_pooler:
        # Supabase transaction pooler (PgBouncer) does not support prepared
        # statements in the default asyncpg cache mode.
        kwargs["connect_args"] = {"statement_cache_size": 0}

    return create_async_engine(url, **kwargs)


def get_engine():
    """Get or create the async engine (singleton)."""
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory():
    """Get or create the async session factory (singleton)."""
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session


async def get_db():
    """FastAPI dependency -- yields an async DB session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def init_db() -> None:
    """Create all tables. Call once on startup.

    If the configured Postgres is unreachable (e.g. IPv6-only DNS on
    Windows, paused Supabase instance), falls back to local SQLite so
    the app can still start for development.
    """
    # Ensure ORM models are imported so metadata.create_all sees them.
    import db_models  # noqa: F401

    global _engine, _async_session

    engine = get_engine()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info(f"Database ready: {config.DATABASE_URL.split('@')[-1].split('/')[0] if '@' in config.DATABASE_URL else 'sqlite'}")
    except Exception as exc:
        if "sqlite" in config.DATABASE_URL:
            raise  # SQLite failures are real errors
        log.warning(f"Cannot reach Postgres ({exc.__class__.__name__}), falling back to SQLite")
        await engine.dispose()
        _engine = None
        _async_session = None
        _sqlite_path = config.BASE_DIR / "vyapari.db"
        config.DATABASE_URL = f"sqlite+aiosqlite:///{_sqlite_path}"
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("Database ready: SQLite (local fallback)")


async def close_db() -> None:
    """Dispose the engine. Call on shutdown."""
    global _engine, _async_session
    if _engine:
        await _engine.dispose()
        _engine = None
        _async_session = None
