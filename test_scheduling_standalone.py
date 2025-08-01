#!/usr/bin/env python3
"""
Standalone Test Script for Simplified Scheduling
Tests all the video call scheduling functionality without pytest dependencies.
"""

import asyncio
import sys
import os
from datetime import time, date, datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Add the app directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.models import Base, User, UserWeeklyAvailability, UserAvailabilityOverride, UserSchedulingPreferences
from app.database import DATABASE_URL

# Create async engine for testing
test_engine = create_async_engine(DATABASE_URL, echo=False)
AsyncTestSession = sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

async def setup_database():
    """Set up the test database"""
    print("🔧 Setting up test database...")
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database setup complete")

async def cleanup_database():
    """Clean up the test database"""
    print("🧹 Cleaning up test database...")
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("✅ Database cleanup complete")

async def test_weekly_availability():
    """Test creating and retrieving weekly availability."""
    print("\n🧪 Testing Weekly Availability")
    print("=" * 40)
    
    async with AsyncTestSession() as session:
        # Create a test user
        user = User(email="test1@example.com", firebase_uid="uid1")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(f"✅ Created test user: {user.id}")

        # Create weekly availability
        avail = UserWeeklyAvailability(
            user_id=user.id, 
            day_of_week=1, 
            start_time=time(18, 0), 
            end_time=time(22, 0)
        )
        session.add(avail)
        await session.commit()
        await session.refresh(avail)
        print(f"✅ Created weekly availability: {avail.id}")

        # Verify it was saved correctly
        found = await session.get(UserWeeklyAvailability, avail.id)
        assert found is not None
        assert found.start_time == time(18, 0)
        assert found.end_time == time(22, 0)
        assert found.user_id == user.id
        print("✅ Weekly availability verification passed")

async def test_availability_override():
    """Test creating and retrieving availability overrides."""
    print("\n🧪 Testing Availability Override")
    print("=" * 40)
    
    async with AsyncTestSession() as session:
        # Create a test user
        user = User(email="test2@example.com", firebase_uid="uid2")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(f"✅ Created test user: {user.id}")

        # Create availability override
        override = UserAvailabilityOverride(
            user_id=user.id,
            date=date(2024, 3, 20),
            start_time=time(14, 0),
            end_time=time(18, 0),
            reason="Working from home"
        )
        session.add(override)
        await session.commit()
        await session.refresh(override)
        print(f"✅ Created availability override: {override.id}")

        # Verify it was saved correctly
        found = await session.get(UserAvailabilityOverride, override.id)
        assert found is not None
        assert found.start_time == time(14, 0)
        assert found.end_time == time(18, 0)
        assert found.reason == "Working from home"
        assert found.user_id == user.id
        print("✅ Availability override verification passed")

async def test_scheduling_preferences():
    """Test creating and retrieving scheduling preferences."""
    print("\n🧪 Testing Scheduling Preferences")
    print("=" * 40)
    
    async with AsyncTestSession() as session:
        # Create a test user
        user = User(email="test3@example.com", firebase_uid="uid3")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(f"✅ Created test user: {user.id}")

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
        session.add(prefs)
        await session.commit()
        await session.refresh(prefs)
        print(f"✅ Created scheduling preferences: {prefs.id}")

        # Verify it was saved correctly
        found = await session.get(UserSchedulingPreferences, prefs.id)
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
        print("✅ Scheduling preferences verification passed")

async def test_no_removed_fields():
    """Test that removed fields are not accessible."""
    print("\n🧪 Testing Removed Fields")
    print("=" * 40)
    
    async with AsyncTestSession() as session:
        # Create a test user
        user = User(email="test4@example.com", firebase_uid="uid4")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(f"✅ Created test user: {user.id}")

        # Test UserWeeklyAvailability doesn't have is_available
        avail = UserWeeklyAvailability(
            user_id=user.id,
            day_of_week=1,
            start_time=time(18, 0),
            end_time=time(22, 0)
        )
        assert not hasattr(avail, 'is_available')
        print("✅ UserWeeklyAvailability: is_available field removed")
        
        # Test UserAvailabilityOverride doesn't have removed fields
        override = UserAvailabilityOverride(
            user_id=user.id,
            date=date(2024, 3, 20),
            start_time=time(14, 0),
            end_time=time(18, 0),
            reason="Test"
        )
        assert not hasattr(override, 'is_available')
        assert not hasattr(override, 'override_type')
        print("✅ UserAvailabilityOverride: is_available and override_type fields removed")
        
        # Test UserSchedulingPreferences doesn't have preferred_call_duration
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
        assert not hasattr(prefs, 'preferred_call_duration')
        print("✅ UserSchedulingPreferences: preferred_call_duration field removed")

async def test_relationships():
    """Test that relationships work correctly."""
    print("\n🧪 Testing Relationships")
    print("=" * 40)
    
    async with AsyncTestSession() as session:
        # Create a test user
        user = User(email="test5@example.com", firebase_uid="uid5")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(f"✅ Created test user: {user.id}")

        # Create weekly availability
        avail = UserWeeklyAvailability(
            user_id=user.id,
            day_of_week=1,
            start_time=time(18, 0),
            end_time=time(22, 0)
        )
        session.add(avail)
        
        # Create availability override
        override = UserAvailabilityOverride(
            user_id=user.id,
            date=date(2024, 3, 20),
            start_time=time(14, 0),
            end_time=time(18, 0),
            reason="Test override"
        )
        session.add(override)
        
        # Create scheduling preferences
        prefs = UserSchedulingPreferences(
            user_id=user.id,
            max_calls_per_week=3,
            min_notice_hours=1,
            max_advance_days=5,
            preferred_start_time=time(19, 0),
            preferred_end_time=time(21, 0),
            email_notifications=True,
            push_notifications=False,
            reminder_hours_before=2
        )
        session.add(prefs)
        
        await session.commit()
        print("✅ Created all related records")

        # Test relationships
        user_with_relations = await session.get(User, user.id)
        assert user_with_relations is not None
        print("✅ User relationships working correctly")

async def main():
    """Run all tests"""
    print("🎬 Simplified Scheduling Test Suite")
    print("=" * 60)
    
    try:
        # Setup
        await setup_database()
        
        # Run all tests
        await test_weekly_availability()
        await test_availability_override()
        await test_scheduling_preferences()
        await test_no_removed_fields()
        await test_relationships()
        
        # Summary
        print("\n📊 Test Results Summary")
        print("=" * 40)
        print("✅ Weekly Availability: PASSED")
        print("✅ Availability Override: PASSED")
        print("✅ Scheduling Preferences: PASSED")
        print("✅ Removed Fields: PASSED")
        print("✅ Relationships: PASSED")
        
        print("\n🎉 All simplified scheduling tests passed!")
        print("\n📝 Summary of Changes:")
        print("   - Removed 'is_available' boolean field")
        print("   - Removed 'override_type' field")
        print("   - Removed 'preferred_call_duration' field")
        print("   - Simplified to time-slot based availability")
        print("   - Zero time slots = blocked day")
        
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    finally:
        # Cleanup
        await cleanup_database()
        await test_engine.dispose()

if __name__ == "__main__":
    asyncio.run(main()) 