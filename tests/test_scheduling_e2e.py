"""
End-to-end tests for the complete When2Meet availability flow
Tests the integration between iOS frontend and Python backend
"""

import pytest
import asyncio
import json
from datetime import datetime, date, time, timedelta
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch

from app.main import app
from app.models import User, UserDefaultAvailability, UserOverrideAvailability
from tests.conftest import TestDatabase


class TestSchedulingEndToEnd:
    """End-to-end tests for scheduling workflow"""

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
                firebase_uid="e2e_test_user",
                email="e2e@example.com",
                name="E2E Test User",
                is_active=True
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            self.user_id = user.id
            return user.id

    def get_auth_headers(self):
        """Get authentication headers for test requests"""
        return {"Authorization": "Bearer e2e_test_user"}

    # MARK: - Complete User Journey Tests

    def test_complete_availability_setup_flow(self):
        """Test complete flow: create user -> set default availability -> add overrides"""
        user_id = asyncio.run(self.create_test_user())
        
        # Step 1: Verify user starts with empty availability
        response = self.client.get(
            f"/availability/default?user_id={user_id}",
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        assert response.json()["time_slots"] == []
        
        # Step 2: Set default availability (typical work hours)
        default_slots = []
        for day in range(1, 6):  # Monday-Friday
            for hour in range(9, 17):  # 9 AM - 5 PM
                for minute in [0, 30]:
                    default_slots.append({
                        "day_of_week": day,
                        "hour": hour,
                        "minute": minute,
                        "is_available": True
                    })
        
        payload = {
            "user_id": user_id,
            "time_slots": default_slots
        }
        
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        assert len(response.json()["time_slots"]) == len(default_slots)
        
        # Step 3: Verify default availability was saved
        response = self.client.get(
            f"/availability/default?user_id={user_id}",
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        saved_slots = response.json()["time_slots"]
        assert len(saved_slots) == len(default_slots)
        
        # Step 4: Add override availability for specific week
        week_start = "2024-01-14"  # Sunday
        
        # First check that no overrides exist
        response = self.client.get(
            f"/availability/override?user_id={user_id}&week_start_date={week_start}",
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        assert response.json()["time_slots"] == []
        
        # Step 5: Create an override (e.g., early meeting on Monday)
        async def create_override():
            async with self.test_db.async_session() as session:
                override = UserOverrideAvailability(
                    user_id=user_id,
                    date=date(2024, 1, 15),  # Monday
                    start_time=time(8, 0),   # 8 AM (earlier than default)
                    end_time=time(8, 30),
                    is_available=True,
                    reason="Early meeting"
                )
                session.add(override)
                await session.commit()
        
        asyncio.run(create_override())
        
        # Step 6: Verify override is returned correctly
        response = self.client.get(
            f"/availability/override?user_id={user_id}&week_start_date={week_start}",
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        override_data = response.json()
        assert len(override_data["time_slots"]) == 1
        
        override_slot = override_data["time_slots"][0]
        assert override_slot["day_of_week"] == 1  # Monday
        assert override_slot["hour"] == 8
        assert override_slot["minute"] == 0
        assert override_slot["is_available"] == True
        assert override_slot["is_override"] == True

    def test_ios_frontend_simulation(self):
        """Simulate iOS frontend behavior with When2Meet grid"""
        user_id = asyncio.run(self.create_test_user())
        
        # Simulate iOS app selecting morning slots for the week
        # This mimics the selectMorningSlots() function in When2MeetViewModel
        calendar_simulation = {
            "weekStartDate": "2024-01-14",  # Sunday
            "selectedSlots": []
        }
        
        # Generate morning slots (6 AM - 12 PM) for Sunday=0 through Saturday=6
        morning_slots = []
        week_start_weekday = 1  # Sunday = 1 in iOS Calendar.weekday
        
        for day_index in range(7):
            day_of_week = ((week_start_weekday + day_index - 1) % 7)  # Convert to Sunday=0
            for hour in range(6, 12):  # 6 AM to 12 PM
                for minute in [0, 30]:
                    morning_slots.append({
                        "id": -1,
                        "day_of_week": day_of_week,
                        "hour": hour,
                        "minute": minute,
                        "is_available": True,
                        "is_override": False
                    })
        
        # Send to backend (simulate iOS BackendService.createDefaultAvailability)
        payload = {
            "user_id": user_id,
            "time_slots": morning_slots
        }
        
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        backend_response = response.json()
        
        # Verify backend returns the same structure iOS expects
        assert "user_id" in backend_response
        assert "time_slots" in backend_response
        assert len(backend_response["time_slots"]) == len(morning_slots)
        
        # Verify day-of-week mapping is consistent
        sunday_slots = [s for s in backend_response["time_slots"] if s["day_of_week"] == 0]
        monday_slots = [s for s in backend_response["time_slots"] if s["day_of_week"] == 1]
        
        assert len(sunday_slots) == 12  # 6 hours * 2 slots per hour
        assert len(monday_slots) == 12
        
        # Test retrieval (simulate app loading saved availability)
        response = self.client.get(
            f"/availability/default?user_id={user_id}",
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        retrieved_data = response.json()
        
        # iOS app should receive the same data structure
        assert len(retrieved_data["time_slots"]) == len(morning_slots)
        
        # Verify Sunday slots are correctly mapped
        retrieved_sunday = [s for s in retrieved_data["time_slots"] if s["day_of_week"] == 0]
        assert len(retrieved_sunday) == 12

    def test_week_navigation_flow(self):
        """Test navigating between weeks with different availability"""
        user_id = asyncio.run(self.create_test_user())
        
        # Set up availability for multiple weeks
        weeks_to_test = [
            "2024-01-07",  # Week 1
            "2024-01-14",  # Week 2
            "2024-01-21",  # Week 3
        ]
        
        # Create different override patterns for each week
        async def create_weekly_overrides():
            async with self.test_db.async_session() as session:
                # Week 1: Monday 9 AM override
                override1 = UserOverrideAvailability(
                    user_id=user_id,
                    date=date(2024, 1, 8),  # Monday week 1
                    start_time=time(9, 0),
                    end_time=time(9, 30),
                    is_available=True,
                    reason="Week 1 meeting"
                )
                session.add(override1)
                
                # Week 2: Tuesday 2 PM override
                override2 = UserOverrideAvailability(
                    user_id=user_id,
                    date=date(2024, 1, 16),  # Tuesday week 2
                    start_time=time(14, 0),
                    end_time=time(14, 30),
                    is_available=True,
                    reason="Week 2 meeting"
                )
                session.add(override2)
                
                # Week 3: No overrides
                
                await session.commit()
        
        asyncio.run(create_weekly_overrides())
        
        # Test each week individually
        for i, week_start in enumerate(weeks_to_test):
            response = self.client.get(
                f"/availability/override?user_id={user_id}&week_start_date={week_start}",
                headers=self.get_auth_headers()
            )
            
            assert response.status_code == 200
            data = response.json()
            
            if i == 0:  # Week 1
                assert len(data["time_slots"]) == 1
                assert data["time_slots"][0]["day_of_week"] == 1  # Monday
                assert data["time_slots"][0]["hour"] == 9
            elif i == 1:  # Week 2
                assert len(data["time_slots"]) == 1
                assert data["time_slots"][0]["day_of_week"] == 2  # Tuesday
                assert data["time_slots"][0]["hour"] == 14
            else:  # Week 3
                assert len(data["time_slots"]) == 0

    def test_drag_selection_simulation(self):
        """Simulate iOS drag selection behavior"""
        user_id = asyncio.run(self.create_test_user())
        
        # Simulate user dragging across multiple time slots
        # This would happen in When2MeetGridView.handleDrag()
        
        # Start with empty selection
        selected_slots = set()
        
        # Simulate drag from Monday 9:00 AM to Monday 11:30 AM
        drag_slots = []
        for hour in range(9, 12):  # 9, 10, 11
            for minute in [0, 30]:
                if hour == 11 and minute == 30:
                    break  # Stop at 11:30
                drag_slots.append({
                    "day_of_week": 1,  # Monday
                    "hour": hour,
                    "minute": minute,
                    "is_available": True,
                    "is_override": False
                })
        
        # Send all selected slots to backend
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
        
        # Verify the drag selection was saved correctly
        response = self.client.get(
            f"/availability/default?user_id={user_id}",
            headers=self.get_auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should have 5 slots: 9:00, 9:30, 10:00, 10:30, 11:00
        monday_slots = [s for s in data["time_slots"] if s["day_of_week"] == 1]
        assert len(monday_slots) == 5
        
        # Verify time sequence
        times = [(s["hour"], s["minute"]) for s in monday_slots]
        times.sort()
        expected_times = [(9, 0), (9, 30), (10, 0), (10, 30), (11, 0)]
        assert times == expected_times

    # MARK: - Error Recovery Tests

    def test_network_failure_recovery(self):
        """Test behavior when network requests fail"""
        user_id = asyncio.run(self.create_test_user())
        
        # Test with malformed JSON
        response = self.client.put(
            "/availability/default",
            data="invalid json",
            headers={**self.get_auth_headers(), "Content-Type": "application/json"}
        )
        
        assert response.status_code == 422  # Validation error
        
        # Verify database wasn't corrupted
        response = self.client.get(
            f"/availability/default?user_id={user_id}",
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        assert response.json()["time_slots"] == []

    def test_partial_failure_handling(self):
        """Test handling of partially valid data"""
        user_id = asyncio.run(self.create_test_user())
        
        # Mix of valid and invalid slots
        mixed_slots = [
            {
                "day_of_week": 0,
                "hour": 9,
                "minute": 0,
                "is_available": True
            },  # Valid
            {
                "day_of_week": 7,  # Invalid
                "hour": 9,
                "minute": 0,
                "is_available": True
            },
            {
                "day_of_week": 1,
                "hour": 10,
                "minute": 0,
                "is_available": True
            }  # Valid
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
        
        # Should succeed but only save valid slots
        assert response.status_code == 200
        data = response.json()
        assert len(data["time_slots"]) == 2  # Only valid slots saved

    # MARK: - Data Consistency Tests

    def test_concurrent_updates(self):
        """Test handling of concurrent availability updates"""
        user_id = asyncio.run(self.create_test_user())
        
        # Simulate two concurrent requests
        slots1 = [{
            "day_of_week": 0,
            "hour": 9,
            "minute": 0,
            "is_available": True
        }]
        
        slots2 = [{
            "day_of_week": 0,
            "hour": 10,
            "minute": 0,
            "is_available": True
        }]
        
        payload1 = {"user_id": user_id, "time_slots": slots1}
        payload2 = {"user_id": user_id, "time_slots": slots2}
        
        # Send both requests
        response1 = self.client.put(
            "/availability/default",
            json=payload1,
            headers=self.get_auth_headers()
        )
        
        response2 = self.client.put(
            "/availability/default",
            json=payload2,
            headers=self.get_auth_headers()
        )
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        # Check final state (last update should win)
        response = self.client.get(
            f"/availability/default?user_id={user_id}",
            headers=self.get_auth_headers()
        )
        
        data = response.json()
        # Should have slots from the last update
        assert len(data["time_slots"]) == 1
        assert data["time_slots"][0]["hour"] == 10

    def test_data_integrity_across_operations(self):
        """Test data integrity across multiple operations"""
        user_id = asyncio.run(self.create_test_user())
        
        # 1. Set initial availability
        initial_slots = [{
            "day_of_week": i,
            "hour": 9,
            "minute": 0,
            "is_available": True
        } for i in range(7)]  # All days at 9 AM
        
        response = self.client.put(
            "/availability/default",
            json={"user_id": user_id, "time_slots": initial_slots},
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        
        # 2. Update with different slots
        updated_slots = [{
            "day_of_week": i,
            "hour": 10,
            "minute": 0,
            "is_available": True
        } for i in range(7)]  # All days at 10 AM
        
        response = self.client.put(
            "/availability/default",
            json={"user_id": user_id, "time_slots": updated_slots},
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        
        # 3. Verify old slots are gone and new slots exist
        response = self.client.get(
            f"/availability/default?user_id={user_id}",
            headers=self.get_auth_headers()
        )
        
        data = response.json()
        hours = [slot["hour"] for slot in data["time_slots"]]
        
        # Should only have 10 AM slots, no 9 AM slots
        assert all(hour == 10 for hour in hours)
        assert 9 not in hours
        assert len(data["time_slots"]) == 7

    # MARK: - Performance Tests

    def test_large_dataset_performance(self):
        """Test performance with realistic large dataset"""
        user_id = asyncio.run(self.create_test_user())
        
        # Create full week availability (7 days * 24 hours * 2 slots = 336 slots)
        all_slots = []
        for day in range(7):
            for hour in range(24):
                for minute in [0, 30]:
                    all_slots.append({
                        "day_of_week": day,
                        "hour": hour,
                        "minute": minute,
                        "is_available": hour >= 9 and hour < 17  # 9-5 available
                    })
        
        payload = {
            "user_id": user_id,
            "time_slots": all_slots
        }
        
        # Time the update operation
        import time
        start_time = time.time()
        
        response = self.client.put(
            "/availability/default",
            json=payload,
            headers=self.get_auth_headers()
        )
        
        end_time = time.time()
        duration = end_time - start_time
        
        assert response.status_code == 200
        assert duration < 5.0  # Should complete within 5 seconds
        
        # Time the retrieval operation
        start_time = time.time()
        
        response = self.client.get(
            f"/availability/default?user_id={user_id}",
            headers=self.get_auth_headers()
        )
        
        end_time = time.time()
        duration = end_time - start_time
        
        assert response.status_code == 200
        assert duration < 2.0  # Should retrieve within 2 seconds
        assert len(response.json()["time_slots"]) == len(all_slots)