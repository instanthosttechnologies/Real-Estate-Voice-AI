from typing import Generator, AsyncGenerator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

# Synchronous engine for robust, thread-safe fast operations & ingestion
sync_db_url = settings.DATABASE_URL
if "postgresql+asyncpg" in sync_db_url:
    sync_db_url = sync_db_url.replace("postgresql+asyncpg", "postgresql+psycopg2")

sync_connect_args = {}
sync_pool_kwargs = {}
if "sqlite" in sync_db_url:
    sync_connect_args["check_same_thread"] = False
    sync_pool_kwargs["poolclass"] = StaticPool

sync_engine = create_engine(
    sync_db_url,
    connect_args=sync_connect_args,
    **sync_pool_kwargs
)

SessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False
)


def get_db() -> Generator[Session, None, None]:
    """Dependency that yields a synchronous database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
