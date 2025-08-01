import pytest
import asyncio
from datetime import time, date
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.models import Base, User, UserWeeklyAvailability, UserAvailabilityOverride, UserSchedulingPreferences
from app.database import DATABASE_URL

# Create async engine for testing
test_engine = create_async_engine(DATABASE_URL, echo=True)
AsyncTestSession = sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

@pytest.fixture(scope="module")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="module", autouse=True)
async def setup_database():
    """Create and drop tables for testing."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture
async def db():
    """Create a database session for testing."""
    async with AsyncTestSession() as session:
        yield session
        await session.rollback()
        await session.close()

@pytest.mark.asyncio
async def test_weekly_availability(db):
    """Test creating and retrieving weekly availability."""
    # Create a test user
    user = User(email="test1@example.com", firebase_uid="uid1")
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Create weekly availability
    avail = UserWeeklyAvailability(
        user_id=user.id, 
        day_of_week=1, 
        start_time=time(18, 0), 
        end_time=time(22, 0)
    )
    db.add(avail)
    await db.commit()
    await db.refresh(avail)

    # Query and verify
    result = await db.execute(
        db.query(UserWeeklyAvailability).filter_by(user_id=user.id, day_of_week=1)
    )
    found = result.scalar_one_or_none()
    
    assert found is not None
    assert found.start_time == time(18, 0)
    assert found.end_time == time(22, 0)
    assert found.user_id == user.id

@pytest.mark.asyncio
async def test_availability_override(db):
    """Test creating and retrieving availability overrides."""
    # Create a test user
    user = User(email="test2@example.com", firebase_uid="uid2")
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Create availability override
    override = UserAvailabilityOverride(
        user_id=user.id,
        date=date(2024, 3, 20),
        start_time=time(14, 0),
        end_time=time(18, 0),
        reason="Working from home"
    )
    db.add(override)
    await db.commit()
    await db.refresh(override)

    # Query and verify
    result = await db.execute(
        db.query(UserAvailabilityOverride).filter_by(user_id=user.id, date=date(2024, 3, 20))
    )
    found = result.scalar_one_or_none()
    
    assert found is not None
    assert found.start_time == time(14, 0)
    assert found.end_time == time(18, 0)
    assert found.reason == "Working from home"
    assert found.user_id == user.id

@pytest.mark.asyncio
async def test_scheduling_preferences(db):
    """Test creating and retrieving scheduling preferences."""
    # Create a test user
    user = User(email="test3@example.com", firebase_uid="uid3")
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Create scheduling preferences
    prefs = UserSchedulingPreferences(
        user_id=user.id,
        max_calls_per_week=5,
        min_notice_hours=2,
        max_advance_days=7,
        preferred_start_time=time(18, 0),
        preferred_end_time=time(22, 0),
        email_notifications=True,
        push_notifications=True,
        reminder_hours_before=1
    )
    db.add(prefs)
    await db.commit()
    await db.refresh(prefs)

    # Query and verify
    result = await db.execute(
        db.query(UserSchedulingPreferences).filter_by(user_id=user.id)
    )
    found = result.scalar_one_or_none()
    
    assert found is not None
    assert found.max_calls_per_week == 5
    assert found.min_notice_hours == 2
    assert found.max_advance_days == 7
    assert found.preferred_start_time == time(18, 0)
    assert found.preferred_end_time == time(22, 0)
    assert found.email_notifications is True
    assert found.push_notifications is True
    assert found.reminder_hours_before == 1
    assert found.user_id == user.id

@pytest.mark.asyncio
async def test_no_removed_fields(db):
    """Test that removed fields (is_available, override_type, preferred_call_duration) are not accessible."""
    # Create a test user
    user = User(email="test4@example.com", firebase_uid="uid4")
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Test that we can't access removed fields
    avail = UserWeeklyAvailability(
        user_id=user.id,
        day_of_week=1,
        start_time=time(18, 0),
        end_time=time(22, 0)
    )
    
    # Verify no is_available attribute exists
    assert not hasattr(avail, 'is_available')
    
    override = UserAvailabilityOverride(
        user_id=user.id,
        date=date(2024, 3, 20),
        start_time=time(14, 0),
        end_time=time(18, 0),
        reason="Test"
    )
    
    # Verify no is_available or override_type attributes exist
    assert not hasattr(override, 'is_available')
    assert not hasattr(override, 'override_type')
    
    prefs = UserSchedulingPreferences(
        user_id=user.id,
        max_calls_per_week=5,
        min_notice_hours=2,
        max_advance_days=7,
        preferred_start_time=time(18, 0),
        preferred_end_time=time(22, 0),
        email_notifications=True,
        push_notifications=True,
        reminder_hours_before=1
    )
    
    # Verify no preferred_call_duration attribute exists
    assert not hasattr(prefs, 'preferred_call_duration')

if __name__ == "__main__":
    # Run tests directly if script is executed
    pytest.main([__file__, "-v"]) 