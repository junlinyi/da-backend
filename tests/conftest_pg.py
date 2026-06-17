"""Postgres-backed test harness for Scheduling V2.

Uses a dedicated test database so partial unique indexes / ARRAY / TIMESTAMPTZ
behave exactly as production. Auth is overridden so tests don't need Firebase.
"""
import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.database import Base
from app.dependencies import get_current_user, get_db
from app.main import app
from app import models

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://dating_user:securepassword@localhost/dating_app_test",
)

engine = create_async_engine(TEST_DB_URL, future=True)
TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with TestSession() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def make_user(db):
    async def _make(name="Test", firebase_uid=None, timezone="UTC", device_token="tok"):
        u = models.User(
            firebase_uid=firebase_uid or f"uid_{name.lower()}",
            name=name, timezone=timezone, device_token=device_token, is_active=True,
        )
        db.add(u); await db.commit(); await db.refresh(u)
        return u
    return _make


@pytest_asyncio.fixture
async def make_match(db):
    async def _make(user_a, user_b, **overrides):
        m = models.Match(
            user_id=user_a.id, matched_user_id=user_b.id, status="accepted",
            user1_status="active", user2_status="active", **overrides,
        )
        db.add(m); await db.commit(); await db.refresh(m)
        return m
    return _make


@pytest_asyncio.fixture
async def client_as(db):
    """Returns a factory: client_as(user) -> AsyncClient authed as that user."""
    def _as(user):
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: user
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    yield _as
    app.dependency_overrides.clear()
