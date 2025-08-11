"""
Integration tests for scheduling.py API endpoints
Tests the When2Meet scheduling system fixes and functionality
"""

import pytest
import asyncio
from datetime import datetime, date, time, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
import json

from app.main import app
from app.database import get_db
from app.models import User, UserDefaultAvailability, UserOverrideAvailability
from tests.conftest import override_get_db, TestDatabase


class TestSchedulingIntegration:
    """Integration tests for scheduling endpoints"""

    @pytest.fixture(autouse=True)
    def setup_method(self, test_db: TestDatabase):
        """Setup method run before each test"""
        self.client = TestClient(app)
        self.test_db = test_db
        self.user_id = None
        
    async def create_test_user(self) -> int:
        """Create a test user and return user ID"""
        async with self.test_db.async_session() as session:
            user = User(
                firebase_uid="test_user_123",
                email="test@example.com",
                name="Test User",
                is_active=True
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            self.user_id = user.id
            return user.id

    def get_auth_headers(self):
        """Get authentication headers for test requests"""
        return {"Authorization": "Bearer test_user_123"}

    # MARK: - Default Availability Tests

    def test_get_default_availability_empty(self):
        """Test getting default availability when none exists"""
        user_id = asyncio.run(self.create_test_user())
        
        response = self.client.get(
            f"/availability/default?user_id={user_id}",
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == user_id
        assert data["time_slots"] == []

    def test_update_default_availability_success(self):
        """Test successful update of default availability"""
        user_id = asyncio.run(self.create_test_user())
        
        # Create test time slots
        time_slots = [
            {
                "day_of_week": 0,  # Sunday
                "hour": 9,
                "minute": 0,
                "is_available": True
            },
            {
                "day_of_week": 0,  # Sunday
                "hour": 9,
                "minute": 30,
                "is_available": True
            },
            {
                "day_of_week": 1,  # Monday
                "hour": 14,
                "minute": 0,
                "is_available": True
            }
        ]
        
        payload = {
            "user_id": user_id,
            "time_slots": time_slots
        }
        
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == user_id
        assert len(data["time_slots"]) == 3

    def test_update_default_availability_validation(self):
        """Test validation of default availability input"""
        user_id = asyncio.run(self.create_test_user())
        
        # Test invalid day_of_week
        invalid_slots = [
            {
                "day_of_week": 7,  # Invalid: should be 0-6
                "hour": 9,
                "minute": 0,
                "is_available": True
            }
        ]
        
        payload = {
            "user_id": user_id,
            "time_slots": invalid_slots
        }
        
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        
        # Should succeed but skip invalid slots
        assert response.status_code == 200
        data = response.json()
        assert len(data["time_slots"]) == 0  # Invalid slot should be skipped

    def test_update_default_availability_hour_validation(self):
        """Test hour validation in default availability"""
        user_id = asyncio.run(self.create_test_user())
        
        # Test invalid hour
        invalid_slots = [
            {
                "day_of_week": 0,
                "hour": 25,  # Invalid: should be 0-23
                "minute": 0,
                "is_available": True
            }
        ]
        
        payload = {
            "user_id": user_id,
            "time_slots": invalid_slots
        }
        
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["time_slots"]) == 0  # Invalid slot should be skipped

    def test_update_default_availability_minute_validation(self):
        """Test minute validation in default availability"""
        user_id = asyncio.run(self.create_test_user())
        
        # Test invalid minute
        invalid_slots = [
            {
                "day_of_week": 0,
                "hour": 9,
                "minute": 15,  # Invalid: should be 0 or 30
                "is_available": True
            }
        ]
        
        payload = {
            "user_id": user_id,
            "time_slots": invalid_slots
        }
        
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["time_slots"]) == 0  # Invalid slot should be skipped

    def test_default_availability_deduplication(self):
        """Test that duplicate slots are properly deduplicated"""
        user_id = asyncio.run(self.create_test_user())
        
        # Create duplicate time slots
        time_slots = [
            {
                "day_of_week": 0,
                "hour": 9,
                "minute": 0,
                "is_available": True
            },
            {
                "day_of_week": 0,
                "hour": 9,
                "minute": 0,
                "is_available": False  # Different availability, same time
            }
        ]
        
        payload = {
            "user_id": user_id,
            "time_slots": time_slots
        }
        
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["time_slots"]) == 1  # Should be deduplicated

    # MARK: - Override Availability Tests

    def test_get_override_availability_empty(self):
        """Test getting override availability when none exists"""
        user_id = asyncio.run(self.create_test_user())
        week_start = "2024-01-14"  # Sunday
        
        response = self.client.get(
            f"/availability/override?user_id={user_id}&week_start_date={week_start}",
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == user_id
        assert data["week_start_date"] == week_start
        assert data["time_slots"] == []

    def test_day_of_week_mapping_fix(self):
        """Test that day-of-week mapping is correct for override availability"""
        user_id = asyncio.run(self.create_test_user())
        
        # Create override availability directly in database
        async def create_override():
            async with self.test_db.async_session() as session:
                # Monday override (should map to day_of_week=1)
                monday_date = date(2024, 1, 15)  # Monday Jan 15, 2024
                override = UserOverrideAvailability(
                    user_id=user_id,
                    date=monday_date,
                    start_time=time(9, 0),
                    end_time=time(9, 30),
                    is_available=True,
                    reason="Test override"
                )
                session.add(override)
                await session.commit()
        
        asyncio.run(create_override())
        
        # Get override availability for the week
        week_start = "2024-01-14"  # Sunday
        response = self.client.get(
            f"/availability/override?user_id={user_id}&week_start_date={week_start}",
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["time_slots"]) == 1
        
        slot = data["time_slots"][0]
        assert slot["day_of_week"] == 1  # Monday should be 1 (not 0)
        assert slot["hour"] == 9
        assert slot["minute"] == 0
        assert slot["is_available"] == True
        assert slot["is_override"] == True

    # MARK: - Edge Cases

    def test_week_boundary_handling(self):
        """Test handling of week boundaries"""
        user_id = asyncio.run(self.create_test_user())
        
        # Test week that spans year boundary
        week_start = "2023-12-31"  # Sunday Dec 31, 2023
        
        response = self.client.get(
            f"/availability/override?user_id={user_id}&week_start_date={week_start}",
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["week_start_date"] == week_start

    def test_leap_year_handling(self):
        """Test handling of leap year dates"""
        user_id = asyncio.run(self.create_test_user())
        
        # Test week containing February 29, 2024
        week_start = "2024-02-25"  # Sunday before leap day
        
        response = self.client.get(
            f"/availability/override?user_id={user_id}&week_start_date={week_start}",
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200

    def test_invalid_week_start_date(self):
        """Test handling of invalid week start date"""
        user_id = asyncio.run(self.create_test_user())
        
        # Invalid date format
        response = self.client.get(
            f"/availability/override?user_id={user_id}&week_start_date=invalid-date",
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 500  # Should handle gracefully

    def test_nonexistent_user(self):
        """Test handling of nonexistent user"""
        response = self.client.get(
            "/availability/default?user_id=99999",
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 404

    # MARK: - Authentication Tests

    def test_missing_authorization_header(self):
        """Test that endpoints require authentication"""
        response = self.client.get("/availability/default?user_id=1")
        
        assert response.status_code == 401

    def test_invalid_authorization_token(self):
        """Test handling of invalid auth token"""
        headers = {"Authorization": "Bearer invalid_token"}
        response = self.client.get(
            "/availability/default?user_id=1",
            headers=headers
        )
        
        assert response.status_code == 401

    # MARK: - Performance Tests

    def test_large_availability_dataset(self):
        """Test performance with large availability dataset"""
        user_id = asyncio.run(self.create_test_user())
        
        # Create large number of time slots (full week, every 30 minutes)
        time_slots = []
        for day in range(7):
            for hour in range(24):
                for minute in [0, 30]:
                    time_slots.append({
                        "day_of_week": day,
                        "hour": hour,
                        "minute": minute,
                        "is_available": True
                    })
        
        payload = {
            "user_id": user_id,
            "time_slots": time_slots
        }
        
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["time_slots"]) == len(time_slots)

    # MARK: - Regression Tests for Fixes

    def test_sunday_equals_zero_regression(self):
        """Regression test: Sunday should equal 0 in day_of_week"""
        user_id = asyncio.run(self.create_test_user())
        
        # Create Sunday availability
        time_slots = [
            {
                "day_of_week": 0,  # Sunday
                "hour": 10,
                "minute": 0,
                "is_available": True
            }
        ]
        
        payload = {
            "user_id": user_id,
            "time_slots": time_slots
        }
        
        # Update availability
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        
        # Retrieve and verify
        response = self.client.get(
            f"/availability/default?user_id={user_id}",
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        sunday_slots = [slot for slot in data["time_slots"] if slot["day_of_week"] == 0]
        assert len(sunday_slots) == 1
        assert sunday_slots[0]["hour"] == 10

    def test_is_available_field_preservation(self):
        """Regression test: is_available field should be preserved from frontend"""
        user_id = asyncio.run(self.create_test_user())
        
        # Create mix of available and unavailable slots
        time_slots = [
            {
                "day_of_week": 0,
                "hour": 9,
                "minute": 0,
                "is_available": True
            },
            {
                "day_of_week": 0,
                "hour": 9,
                "minute": 30,
                "is_available": False
            }
        ]
        
        payload = {
            "user_id": user_id,
            "time_slots": time_slots
        }
        
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        
        # Verify availability values are preserved
        response = self.client.get(
            f"/availability/default?user_id={user_id}",
            headers=self.get_auth_headers()
        )
        
        data = response.json()
        slots_by_minute = {slot["minute"]: slot for slot in data["time_slots"]}
        
        assert slots_by_minute[0]["is_available"] == True
        assert slots_by_minute[30]["is_available"] == False


# MARK: - Test Fixtures and Utilities

@pytest.fixture
async def test_user(test_db: TestDatabase) -> User:
    """Create a test user"""
    async with test_db.async_session() as session:
        user = User(
            firebase_uid="test_fixture_user",
            email="fixture@example.com",
            name="Fixture User",
            is_active=True
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
def sample_time_slots():
    """Sample time slots for testing"""
    return [
        {
            "day_of_week": 0,  # Sunday
            "hour": 9,
            "minute": 0,
            "is_available": True
        },
        {
            "day_of_week": 1,  # Monday
            "hour": 14,
            "minute": 30,
            "is_available": True
        },
        {
            "day_of_week": 5,  # Friday
            "hour": 18,
            "minute": 0,
            "is_available": False
        }
    ]


# MARK: - Cleanup

@pytest.fixture(autouse=True)
async def cleanup_database(test_db: TestDatabase):
    """Clean up database after each test"""
    yield
    async with test_db.async_session() as session:
        await session.execute(delete(UserDefaultAvailability))
        await session.execute(delete(UserOverrideAvailability))
        await session.execute(delete(User))
        await session.commit()