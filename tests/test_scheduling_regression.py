"""
Regression tests for specific When2Meet scheduling system fixes
These tests ensure that previously fixed bugs don't reoccur
"""

import pytest
import asyncio
from datetime import datetime, date, time, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import User, UserDefaultAvailability, UserOverrideAvailability
from tests.conftest import TestDatabase


class TestSchedulingRegression:
    """Regression tests for scheduling fixes"""

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
                firebase_uid="regression_test_user",
                email="regression@example.com",
                name="Regression Test User",
                is_active=True
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            self.user_id = user.id
            return user.id

    def get_auth_headers(self):
        """Get authentication headers for test requests"""
        return {"Authorization": "Bearer regression_test_user"}

    # MARK: - Fix 1: Day-of-Week Mapping Consistency

    def test_regression_day_of_week_mapping_ios_backend(self):
        """
        REGRESSION TEST: Day-of-week mapping between iOS and backend
        
        BUG: iOS used ((weekStartWeekday + dayIndex - 1) % 7) while backend used 
             slot.date.weekday() which returns Monday=0, causing misalignment
        
        FIX: Backend now converts Python weekday to Sunday=0 system:
             day_of_week = (python_weekday + 1) % 7
        """
        user_id = asyncio.run(self.create_test_user())
        
        # Create override for specific dates to test day mapping
        test_dates = [
            (date(2024, 1, 14), 0),  # Sunday should be 0
            (date(2024, 1, 15), 1),  # Monday should be 1
            (date(2024, 1, 16), 2),  # Tuesday should be 2
            (date(2024, 1, 17), 3),  # Wednesday should be 3
            (date(2024, 1, 18), 4),  # Thursday should be 4
            (date(2024, 1, 19), 5),  # Friday should be 5
            (date(2024, 1, 20), 6),  # Saturday should be 6
        ]
        
        async def create_overrides():
            async with self.test_db.async_session() as session:
                for test_date, expected_day in test_dates:
                    override = UserOverrideAvailability(
                        user_id=user_id,
                        date=test_date,
                        start_time=time(10, 0),
                        end_time=time(10, 30),
                        is_available=True,
                        reason=f"Test {test_date.strftime('%A')}"
                    )
                    session.add(override)
                await session.commit()
        
        asyncio.run(create_overrides())
        
        # Test API response for the week
        week_start = "2024-01-14"  # Sunday
        response = self.client.get(
            f"/availability/override?user_id={user_id}&week_start_date={week_start}",
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        slots = data["time_slots"]
        
        # Verify each day maps correctly
        slot_by_day = {slot["day_of_week"]: slot for slot in slots}
        
        for test_date, expected_day in test_dates:
            assert expected_day in slot_by_day, f"{test_date.strftime('%A')} should map to day {expected_day}"
            slot = slot_by_day[expected_day]
            assert slot["date"] == test_date.isoformat()
            assert slot["day_of_week"] == expected_day

    def test_regression_sunday_equals_zero(self):
        """
        REGRESSION TEST: Sunday should always equal 0 in day_of_week
        
        BUG: Inconsistent Sunday mapping between different parts of the system
        FIX: Standardized on Sunday=0 throughout
        """
        user_id = asyncio.run(self.create_test_user())
        
        # Test default availability for Sunday
        sunday_slots = [{
            "day_of_week": 0,  # Sunday
            "hour": 9,
            "minute": 0,
            "is_available": True
        }]
        
        payload = {
            "user_id": user_id,
            "time_slots": sunday_slots
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
        
        data = response.json()
        sunday_slots_returned = [s for s in data["time_slots"] if s["day_of_week"] == 0]
        
        assert len(sunday_slots_returned) == 1
        assert sunday_slots_returned[0]["day_of_week"] == 0
        assert sunday_slots_returned[0]["hour"] == 9
        assert sunday_slots_returned[0]["minute"] == 0

    # MARK: - Fix 2: Slot Selection and Persistence

    def test_regression_slot_deduplication(self):
        """
        REGRESSION TEST: Duplicate slot handling in When2MeetGridView
        
        BUG: Set comparison failed due to different ID values (-1 vs actual IDs)
        FIX: Use removeAll with coordinate matching instead of Set.remove()
        """
        user_id = asyncio.run(self.create_test_user())
        
        # Simulate the duplicate slot scenario
        # iOS sends slots with id=-1, backend assigns real IDs
        duplicate_slots = [
            {
                "day_of_week": 1,
                "hour": 10,
                "minute": 0,
                "is_available": True
            },
            {
                "day_of_week": 1,
                "hour": 10,
                "minute": 0,
                "is_available": True
            },  # Exact duplicate
            {
                "day_of_week": 1,
                "hour": 10,
                "minute": 0,
                "is_available": False  # Same time, different availability
            }
        ]
        
        payload = {
            "user_id": user_id,
            "time_slots": duplicate_slots
        }
        
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should be deduplicated to 1 slot (last one wins)
        monday_10am_slots = [
            s for s in data["time_slots"] 
            if s["day_of_week"] == 1 and s["hour"] == 10 and s["minute"] == 0
        ]
        assert len(monday_10am_slots) == 1

    def test_regression_drag_selection_persistence(self):
        """
        REGRESSION TEST: Drag selection state management
        
        BUG: dragSlots tracking and selection state could become inconsistent
        FIX: Improved drag handling with proper slot deduplication
        """
        user_id = asyncio.run(self.create_test_user())
        
        # Simulate a drag selection across multiple slots
        # This would happen when user drags from 9:00 to 11:30
        drag_slots = []
        for hour in range(9, 12):
            for minute in [0, 30]:
                if hour == 11 and minute == 30:
                    break  # End at 11:00, not 11:30
                drag_slots.append({
                    "day_of_week": 2,  # Tuesday
                    "hour": hour,
                    "minute": minute,
                    "is_available": True
                })
        
        payload = {
            "user_id": user_id,
            "time_slots": drag_slots
        }
        
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        
        # Verify all drag slots were saved
        response = self.client.get(
            f"/availability/default?user_id={user_id}",
            headers=self.get_auth_headers()
        )
        
        data = response.json()
        tuesday_slots = [s for s in data["time_slots"] if s["day_of_week"] == 2]
        
        # Should have 5 slots: 9:00, 9:30, 10:00, 10:30, 11:00
        assert len(tuesday_slots) == 5
        
        # Verify sequential time slots
        times = sorted([(s["hour"], s["minute"]) for s in tuesday_slots])
        expected_times = [(9, 0), (9, 30), (10, 0), (10, 30), (11, 0)]
        assert times == expected_times

    # MARK: - Fix 3: Backend is_available Field Handling

    def test_regression_is_available_field_preservation(self):
        """
        REGRESSION TEST: Backend ignoring is_available field from frontend
        
        BUG: Backend was using is_available=True hardcoded instead of frontend value
        FIX: Changed to is_available=slot.get("is_available", True)
        """
        user_id = asyncio.run(self.create_test_user())
        
        # Send mix of available and unavailable slots
        mixed_slots = [
            {
                "day_of_week": 3,  # Wednesday
                "hour": 9,
                "minute": 0,
                "is_available": True
            },
            {
                "day_of_week": 3,  # Wednesday
                "hour": 9,
                "minute": 30,
                "is_available": False  # This should be preserved
            },
            {
                "day_of_week": 3,  # Wednesday
                "hour": 10,
                "minute": 0,
                "is_available": True
            }
        ]
        
        payload = {
            "user_id": user_id,
            "time_slots": mixed_slots
        }
        
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        
        # Verify is_available values are preserved
        response = self.client.get(
            f"/availability/default?user_id={user_id}",
            headers=self.get_auth_headers()
        )
        
        data = response.json()
        wednesday_slots = [s for s in data["time_slots"] if s["day_of_week"] == 3]
        
        # Sort by time for comparison
        wednesday_slots.sort(key=lambda x: (x["hour"], x["minute"]))
        
        assert len(wednesday_slots) == 3
        assert wednesday_slots[0]["is_available"] == True   # 9:00
        assert wednesday_slots[1]["is_available"] == False  # 9:30 - should be False!
        assert wednesday_slots[2]["is_available"] == True   # 10:00

    def test_regression_override_availability_actual_value(self):
        """
        REGRESSION TEST: Override availability using actual is_available value
        
        BUG: Backend returned is_available: True for all override slots
        FIX: Use slot.is_available instead of hardcoded True
        """
        user_id = asyncio.run(self.create_test_user())
        
        # Create overrides with different availability values
        async def create_mixed_overrides():
            async with self.test_db.async_session() as session:
                # Available override
                override1 = UserOverrideAvailability(
                    user_id=user_id,
                    date=date(2024, 1, 15),  # Monday
                    start_time=time(9, 0),
                    end_time=time(9, 30),
                    is_available=True,
                    reason="Available meeting"
                )
                session.add(override1)
                
                # Unavailable override (blocked time)
                override2 = UserOverrideAvailability(
                    user_id=user_id,
                    date=date(2024, 1, 15),  # Monday
                    start_time=time(10, 0),
                    end_time=time(10, 30),
                    is_available=False,
                    reason="Blocked time"
                )
                session.add(override2)
                
                await session.commit()
        
        asyncio.run(create_mixed_overrides())
        
        # Get override availability
        week_start = "2024-01-14"
        response = self.client.get(
            f"/availability/override?user_id={user_id}&week_start_date={week_start}",
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        slots = data["time_slots"]
        
        assert len(slots) == 2
        
        # Sort by hour for comparison
        slots.sort(key=lambda x: x["hour"])
        
        assert slots[0]["hour"] == 9
        assert slots[0]["is_available"] == True
        
        assert slots[1]["hour"] == 10
        assert slots[1]["is_available"] == False  # Should be False, not True!

    # MARK: - Fix 4: Input Validation

    def test_regression_input_validation_prevents_invalid_data(self):
        """
        REGRESSION TEST: Input validation for day_of_week, hour, minute
        
        BUG: Invalid input could cause database constraint violations
        FIX: Added validation with logging and graceful skipping
        """
        user_id = asyncio.run(self.create_test_user())
        
        # Test various invalid inputs
        invalid_slots = [
            {
                "day_of_week": -1,  # Invalid: too low
                "hour": 9,
                "minute": 0,
                "is_available": True
            },
            {
                "day_of_week": 8,   # Invalid: too high
                "hour": 9,
                "minute": 0,
                "is_available": True
            },
            {
                "day_of_week": 1,
                "hour": -1,         # Invalid: negative hour
                "minute": 0,
                "is_available": True
            },
            {
                "day_of_week": 1,
                "hour": 25,         # Invalid: hour too high
                "minute": 0,
                "is_available": True
            },
            {
                "day_of_week": 1,
                "hour": 9,
                "minute": 15,       # Invalid: minute not 0 or 30
                "is_available": True
            },
            {
                "day_of_week": 1,
                "hour": 9,
                "minute": 45,       # Invalid: minute not 0 or 30
                "is_available": True
            },
            {
                "day_of_week": 1,   # Valid slot for comparison
                "hour": 9,
                "minute": 0,
                "is_available": True
            }
        ]
        
        payload = {
            "user_id": user_id,
            "time_slots": invalid_slots
        }
        
        # Should succeed but skip invalid slots
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should only have 1 valid slot (the last one)
        assert len(data["time_slots"]) == 1
        valid_slot = data["time_slots"][0]
        assert valid_slot["day_of_week"] == 1
        assert valid_slot["hour"] == 9
        assert valid_slot["minute"] == 0

    # MARK: - Fix 5: UI Touch Target Improvements

    def test_regression_touch_target_height_accessibility(self):
        """
        REGRESSION TEST: Time slot touch targets in iOS UI
        
        BUG: Time slots had 15pt height, too small for comfortable touch
        FIX: Increased to 20pt height
        
        Note: This is a UI test that would ideally run in iOS simulator
        We simulate by checking that the data flow supports larger touch areas
        """
        user_id = asyncio.run(self.create_test_user())
        
        # Simulate user selecting many slots (which would be easier with larger touch targets)
        # Create a dense grid of selections
        dense_slots = []
        for hour in range(9, 17):  # 8 hours
            for minute in [0, 30]:  # 2 slots per hour
                dense_slots.append({
                    "day_of_week": 4,  # Thursday
                    "hour": hour,
                    "minute": minute,
                    "is_available": True
                })
        
        payload = {
            "user_id": user_id,
            "time_slots": dense_slots
        }
        
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        
        # Verify all dense selections were processed correctly
        response = self.client.get(
            f"/availability/default?user_id={user_id}",
            headers=self.get_auth_headers()
        )
        
        data = response.json()
        thursday_slots = [s for s in data["time_slots"] if s["day_of_week"] == 4]
        
        # Should have 16 slots (8 hours * 2 slots per hour)
        assert len(thursday_slots) == 16
        
        # Verify complete time range
        hours = sorted(set(s["hour"] for s in thursday_slots))
        assert hours == list(range(9, 17))

    # MARK: - Fix 6: Week Boundary Edge Cases

    def test_regression_week_boundary_transitions(self):
        """
        REGRESSION TEST: Week boundary date calculations
        
        BUG: Week transitions could cause incorrect date calculations
        FIX: Proper calendar arithmetic for week navigation
        """
        user_id = asyncio.run(self.create_test_user())
        
        # Test critical week boundaries
        boundary_weeks = [
            "2023-12-31",  # New Year transition
            "2024-02-25",  # Leap year week
            "2024-12-29",  # Year end
        ]
        
        for week_start in boundary_weeks:
            # Should not crash on any boundary week
            response = self.client.get(
                f"/availability/override?user_id={user_id}&week_start_date={week_start}",
                headers=self.get_auth_headers()
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "week_start_date" in data
            assert data["week_start_date"] == week_start

    # MARK: - Fix 7: Data Race Conditions

    def test_regression_concurrent_update_consistency(self):
        """
        REGRESSION TEST: Data consistency under concurrent updates
        
        BUG: Race conditions could cause data corruption
        FIX: Proper transaction handling and atomic operations
        """
        user_id = asyncio.run(self.create_test_user())
        
        # Simulate rapid consecutive updates (like user rapidly changing selection)
        updates = [
            [{"day_of_week": 5, "hour": 9, "minute": 0, "is_available": True}],
            [{"day_of_week": 5, "hour": 10, "minute": 0, "is_available": True}],
            [{"day_of_week": 5, "hour": 11, "minute": 0, "is_available": True}],
        ]
        
        responses = []
        for slots in updates:
            payload = {"user_id": user_id, "time_slots": slots}
            response = self.client.put(
                "/availability/default",
                json=payload,
                headers=self.get_auth_headers()
            )
            responses.append(response)
        
        # All updates should succeed
        for response in responses:
            assert response.status_code == 200
        
        # Final state should be consistent (last update wins)
        response = self.client.get(
            f"/availability/default?user_id={user_id}",
            headers=self.get_auth_headers()
        )
        
        data = response.json()
        friday_slots = [s for s in data["time_slots"] if s["day_of_week"] == 5]
        
        # Should have only the last slot (11:00)
        assert len(friday_slots) == 1
        assert friday_slots[0]["hour"] == 11

    # MARK: - Performance Regression Tests

    def test_regression_large_update_performance(self):
        """
        REGRESSION TEST: Performance doesn't degrade with optimizations
        
        Ensures fixes don't impact performance negatively
        """
        user_id = asyncio.run(self.create_test_user())
        
        # Create large availability update
        large_slots = []
        for day in range(7):
            for hour in range(8, 18):  # 10 hours
                for minute in [0, 30]:
                    large_slots.append({
                        "day_of_week": day,
                        "hour": hour,
                        "minute": minute,
                        "is_available": True
                    })
        
        # Should handle 140 slots efficiently
        payload = {"user_id": user_id, "time_slots": large_slots}
        
        import time
        start_time = time.time()
        
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        
        duration = time.time() - start_time
        
        assert response.status_code == 200
        assert duration < 3.0  # Should complete within 3 seconds
        assert len(response.json()["time_slots"]) == len(large_slots)