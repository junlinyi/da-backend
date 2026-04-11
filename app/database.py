# app/database.py

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import create_engine
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://dating_user:securepassword@localhost/dating_app")
SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")

# Create async engine
engine = create_async_engine(DATABASE_URL, echo=False)

# Create sync engine for sync service
sync_engine = create_engine(SYNC_DATABASE_URL, echo=False)

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
