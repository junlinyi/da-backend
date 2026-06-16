"""
Pytest configuration and fixtures for When2Meet scheduling tests
"""

import pytest
import asyncio
from typing import AsyncGenerator, Generator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from httpx import AsyncClient
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db, Base
from app.models import User


class TestDatabase:
    """Test database configuration"""
    
    def __init__(self):
        # Use in-memory SQLite for tests
        self.database_url = "sqlite+aiosqlite:///./test.db"
        self.sync_database_url = "sqlite:///./test.db"
        
        # Create async engine
        self.async_engine = create_async_engine(
            self.database_url,
            echo=False,  # Set to True for SQL debugging
            connect_args={"check_same_thread": False}
        )
        
        # Create sync engine for setup/teardown
        self.sync_engine = create_engine(
            self.sync_database_url,
            echo=False,
            connect_args={"check_same_thread": False}
        )
        
        # Create session factories
        self.async_session_factory = sessionmaker(
            bind=self.async_engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
    
    def async_session(self) -> AsyncSession:
        """Get async database session"""
        return self.async_session_factory()
    
    async def create_tables(self):
        """Create all database tables"""
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def drop_tables(self):
        """Drop all database tables"""
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


# Global test database instance
test_db_instance = TestDatabase()


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    """Override dependency for test database"""
    async with test_db_instance.async_session() as session:
        yield session


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_db() -> TestDatabase:
    """Provide test database instance"""
    await test_db_instance.create_tables()
    yield test_db_instance
    await test_db_instance.drop_tables()


@pytest.fixture(autouse=True)
async def setup_database(request):
    """Setup the SQLite database for each test.

    Skips entirely for tests that use the Postgres harness (`conftest_pg.py`),
    detected via the `db` fixture, so the broken SQLite ARRAY setup never runs
    for those tests.
    """
    if "db" in request.fixturenames:
        yield
        return
    test_db = request.getfixturevalue("test_db")
    # Override the dependency
    app.dependency_overrides[get_db] = override_get_db
    yield
    # Clean up
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Provide test client"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
async def async_client(test_db: TestDatabase) -> AsyncGenerator[AsyncClient, None]:
    """Provide async test client"""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def test_user(test_db: TestDatabase) -> User:
    """Create a test user"""
    async with test_db.async_session() as session:
        user = User(
            firebase_uid="test_user_fixture",
            email="fixture@example.com",
            name="Test User",
            is_active=True
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
def auth_headers() -> dict:
    """Provide authentication headers for tests"""
    return {"Authorization": "Bearer test_user_fixture"}


# Test data fixtures

@pytest.fixture
def sample_time_slots():
    """Sample time slots for testing"""
    return [
        {
            "day_of_week": 1,  # Monday
            "hour": 9,
            "minute": 0,
            "is_available": True
        },
        {
            "day_of_week": 1,  # Monday
            "hour": 9,
            "minute": 30,
            "is_available": True
        },
        {
            "day_of_week": 2,  # Tuesday
            "hour": 14,
            "minute": 0,
            "is_available": False
        }
    ]


@pytest.fixture
def week_boundary_dates():
    """Week boundary dates for testing"""
    return [
        "2023-12-31",  # New Year
        "2024-02-25",  # Leap year
        "2024-12-29",  # Year end
    ]


@pytest.fixture
def invalid_time_slots():
    """Invalid time slots for validation testing"""
    return [
        {"day_of_week": -1, "hour": 9, "minute": 0, "is_available": True},
        {"day_of_week": 7, "hour": 9, "minute": 0, "is_available": True},
        {"day_of_week": 1, "hour": 25, "minute": 0, "is_available": True},
        {"day_of_week": 1, "hour": 9, "minute": 15, "is_available": True},
    ]


# Performance testing fixtures

@pytest.fixture
def large_time_slots():
    """Large dataset of time slots for performance testing"""
    slots = []
    for day in range(7):
        for hour in range(24):
            for minute in [0, 30]:
                slots.append({
                    "day_of_week": day,
                    "hour": hour,
                    "minute": minute,
                    "is_available": True
                })
    return slots


# Cleanup fixtures

@pytest.fixture(autouse=True)
async def cleanup_after_test(request):
    """Clean up after each test.

    Skipped for Postgres-harness tests (those that use the `db` fixture), which
    manage their own teardown.
    """
    if "db" in request.fixturenames:
        yield
        return
    test_db = request.getfixturevalue("test_db")
    yield
    # Clean up any test data
    async with test_db.async_session() as session:
        # Add cleanup logic if needed
        await session.commit()


# Markers for test categorization

def pytest_configure(config):
    """Configure pytest markers"""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "e2e: End-to-end tests")
    config.addinivalue_line("markers", "regression: Regression tests")
    config.addinivalue_line("markers", "performance: Performance tests")
    config.addinivalue_line("markers", "slow: Slow running tests")


# Test collection customization

def pytest_collection_modifyitems(config, items):
    """Modify test collection"""
    for item in items:
        # Add markers based on test file names
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
        elif "e2e" in item.nodeid:
            item.add_marker(pytest.mark.e2e)
        elif "regression" in item.nodeid:
            item.add_marker(pytest.mark.regression)
        elif "performance" in item.nodeid:
            item.add_marker(pytest.mark.performance)
        else:
            item.add_marker(pytest.mark.unit)