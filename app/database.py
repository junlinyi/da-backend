# app/database.py

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://dating_user:securepassword@localhost/dating_app")

# Create async engine
engine = create_async_engine(DATABASE_URL, echo=True)

# Create session factory
SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

# Declare Base for models
Base = declarative_base()

# Dependency to get the database session
async def get_db():
    async with SessionLocal() as session:
        yield session
