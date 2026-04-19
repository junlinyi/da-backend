# app/database.py

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import create_engine
import os
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://dating_user:securepassword@localhost/dating_app")

# Normalize to async URL — Railway injects postgresql:// or postgres://, asyncpg needs postgresql+asyncpg://
if _raw_url.startswith("postgres://"):
    DATABASE_URL = _raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif _raw_url.startswith("postgresql://") and "+asyncpg" not in _raw_url:
    DATABASE_URL = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = _raw_url

# Sync URL strips the async driver back to standard postgresql://
SYNC_DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

# Create async engine with production-grade pool settings
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=20,        # Base number of persistent connections
    max_overflow=10,     # Extra connections allowed when pool is exhausted
    pool_pre_ping=True,  # Test connection health before use (avoids stale-connection errors)
    pool_recycle=3600,   # Recycle connections after 1 hour to avoid DB-side timeout drops
)

# Create sync engine for sync service
sync_engine = create_engine(
    SYNC_DATABASE_URL,
    echo=False,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
    pool_recycle=3600,
)

# Create session factory
SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

# Create sync session factory
SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)

# Declare Base for models
Base = declarative_base()

# Dependency to get the database session
async def get_db():
    async with SessionLocal() as session:
        yield session

# Dependency to get the sync database session
def get_db_sync():
    session = SyncSessionLocal()
    try:
        yield session
    finally:
        session.close()
