"""
Integration tests for override availability functionality
Tests the save/load persistence issues and rolling date support
"""

import pytest
import asyncio
import json
from datetime import datetime, date, timedelta
import requests
import sys
import os

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

BASE_URL = "http://localhost:8000"

class TestOverrideAvailability:
    """Test override availability save/load functionality with rolling dates"""
    
    def test_override_save_load_roundtrip(self):
        """Test that override availability can be saved and loaded correctly"""
        user_id = 75
        today = date.today()
        
        # Test data: 3+ slots with different availability
        test_slots = [
            {
                "id": 10000,
                "day_of_week": 0,  # Sunday
                "hour": 14,
                "minute": 0,
                "is_available": True,
                "is_override": True
            },
            {
                "id": 10030,
                "day_of_week": 0,  # Sunday  
                "hour": 14,
                "minute": 30,
                "is_available": True,
                "is_override": True
            },
            {
                "id": 11500,
                "day_of_week": 1,  # Monday
                "hour": 15,
                "minute": 0,
                "is_available": True,
                "is_override": True
            },
            {
                "id": 22000,
                "day_of_week": 2,  # Tuesday
                "hour": 20,
                "minute": 0,
                "is_available": True,
                "is_override": True
            }
        ]
        
        # Step 1: Save override availability
        save_payload = {
            "user_id": user_id,
            "start_date": today.isoformat(),  # Use rolling start_date
            "time_slots": test_slots
        }
        
        print(f"🧪 [TEST] Saving override with {len(test_slots)} slots for user {user_id}, start_date={today}")
        
        save_response = requests.put(
            f"{BASE_URL}/scheduling/availability/override",
            json=save_payload,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"🧪 [TEST] Save response status: {save_response.status_code}")
        if save_response.status_code != 200:
            print(f"🧪 [TEST] Save response body: {save_response.text}")
        
        assert save_response.status_code == 200
        save_data = save_response.json()
        print(f"🧪 [TEST] Save successful, returned {len(save_data.get('time_slots', []))} slots")
        
        # Step 2: Load override availability using rolling start_date
        load_response = requests.get(
            f"{BASE_URL}/scheduling/availability/override",
            params={
                "user_id": user_id,
                "start_date": today.isoformat()  # Use rolling start_date
            }
        )
        
        print(f"🧪 [TEST] Load response status: {load_response.status_code}")
        if load_response.status_code != 200:
            print(f"🧪 [TEST] Load response body: {load_response.text}")
            
        assert load_response.status_code == 200
        load_data = load_response.json()
        
        loaded_slots = load_data.get("time_slots", [])
        available_loaded_slots = [slot for slot in loaded_slots if slot.get("is_available", False)]
        
        print(f"🧪 [TEST] Load successful, got {len(loaded_slots)} total slots, {len(available_loaded_slots)} available")
        
        # Step 3: Verify the saved slots match the loaded slots
        assert len(available_loaded_slots) == len(test_slots), f"Expected {len(test_slots)} available slots, got {len(available_loaded_slots)}"
        
        # Check that each test slot is present in the loaded data
        for test_slot in test_slots:
            matching_slot = None
            for loaded_slot in available_loaded_slots:
                if (loaded_slot["day_of_week"] == test_slot["day_of_week"] and 
                    loaded_slot["hour"] == test_slot["hour"] and 
                    loaded_slot["minute"] == test_slot["minute"]):
                    matching_slot = loaded_slot
                    break
            
            assert matching_slot is not None, f"Test slot not found in loaded data: {test_slot}"
            assert matching_slot["is_available"] == True, f"Slot should be available: {test_slot}"
            assert matching_slot["is_override"] == True, f"Slot should be override: {test_slot}"
            
        print("✅ [TEST] Override save/load roundtrip test passed!")
        
    def test_rolling_vs_traditional_week_start(self):
        """Test the difference between rolling start_date and traditional week_start_date"""
        user_id = 75
        today = date.today()
        
        # Get traditional week start (Sunday)
        days_since_sunday = (today.weekday() + 1) % 7  # Monday=0 -> Sunday=0
        traditional_week_start = today - timedelta(days=days_since_sunday)
        
        print(f"🧪 [TEST] Today: {today}, Traditional week start: {traditional_week_start}")
        
        # Save some override data using rolling start_date
        test_slots = [
            {
                "id": 10000,
                "day_of_week": (today.weekday() + 1) % 7,  # Today's day_of_week
                "hour": 10,
                "minute": 0,
                "is_available": True,
                "is_override": True
            }
        ]
        
        save_payload = {
            "user_id": user_id,
            "start_date": today.isoformat(),
            "time_slots": test_slots
        }
        
        save_response = requests.put(
            f"{BASE_URL}/scheduling/availability/override",
            json=save_payload
        )
        assert save_response.status_code == 200
        
        # Test 1: Load with rolling start_date (should find the slot)
        rolling_response = requests.get(
            f"{BASE_URL}/scheduling/availability/override",
            params={
                "user_id": user_id,
                "start_date": today.isoformat()
            }
        )
        assert rolling_response.status_code == 200
        rolling_data = rolling_response.json()
        rolling_available = [s for s in rolling_data["time_slots"] if s["is_available"]]
        
        print(f"🧪 [TEST] Rolling start_date found {len(rolling_available)} available slots")
        
        # Test 2: Load with traditional week_start_date (may or may not find the slot depending on dates)
        traditional_response = requests.get(
            f"{BASE_URL}/scheduling/availability/override", 
            params={
                "user_id": user_id,
                "week_start_date": traditional_week_start.isoformat()
            }
        )
        
        if traditional_response.status_code == 200:
            traditional_data = traditional_response.json()
            traditional_available = [s for s in traditional_data["time_slots"] if s["is_available"]]
            print(f"🧪 [TEST] Traditional week_start_date found {len(traditional_available)} available slots")
        else:
            print(f"🧪 [TEST] Traditional week_start_date failed with status {traditional_response.status_code}")
        
        # The rolling approach should always find the slot we just saved
        assert len(rolling_available) >= 1, "Rolling start_date should find the saved slot"
        
        print("✅ [TEST] Rolling vs traditional week start test passed!")
        
    def test_multiple_days_override(self):
        """Test saving override slots across multiple days in the rolling 7-day window"""
        user_id = 75
        today = date.today()
        
        # Create slots for different days of the week (0-6, Sunday-Saturday)
        test_slots = []
        for day_offset in range(5):  # Test 5 days
            target_date = today + timedelta(days=day_offset)
            day_of_week = (target_date.weekday() + 1) % 7  # Convert to Sunday=0
            
            test_slots.append({
                "id": day_offset * 10000 + 1200,
                "day_of_week": day_of_week,
                "hour": 12,
                "minute": 0,
                "is_available": True,
                "is_override": True
            })
        
        print(f"🧪 [TEST] Saving {len(test_slots)} slots across multiple days")
        
        # Save the slots
        save_payload = {
            "user_id": user_id,
            "start_date": today.isoformat(),
            "time_slots": test_slots
        }
        
        save_response = requests.put(
            f"{BASE_URL}/scheduling/availability/override",
            json=save_payload
        )
        assert save_response.status_code == 200
        
        # Load and verify
        load_response = requests.get(
            f"{BASE_URL}/scheduling/availability/override",
            params={
                "user_id": user_id,
                "start_date": today.isoformat()
            }
        )
        assert load_response.status_code == 200
        
        load_data = load_response.json()
        available_slots = [s for s in load_data["time_slots"] if s["is_available"]]
        
        print(f"🧪 [TEST] Loaded {len(available_slots)} available slots")
        
        assert len(available_slots) == len(test_slots), f"Expected {len(test_slots)} available slots, got {len(available_slots)}"
        
        print("✅ [TEST] Multiple days override test passed!")

def run_tests():
    """Run the tests manually without pytest for simpler execution"""
    print("🧪 [TEST] Starting override availability integration tests...")
    
    # Check if server is running
    try:
        response = requests.get(f"{BASE_URL}/docs")
        if response.status_code == 200:
            print("✅ [TEST] Backend server is running")
        else:
            print("❌ [TEST] Backend server returned unexpected status")
            return
    except requests.exceptions.ConnectionError:
        print("❌ [TEST] Backend server is not running. Start with:")
        print("cd ~/GitHub2/da-backend && source venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
        return
    
    test_instance = TestOverrideAvailability()
    
    try:
        print("\n🧪 [TEST] Test 1: Override save/load roundtrip")
        test_instance.test_override_save_load_roundtrip()
        print("✅ [TEST] Test 1 passed")
        
        print("\n🧪 [TEST] Test 2: Rolling vs traditional week start")
        test_instance.test_rolling_vs_traditional_week_start()
        print("✅ [TEST] Test 2 passed")
        
        print("\n🧪 [TEST] Test 3: Multiple days override")
        test_instance.test_multiple_days_override()
        print("✅ [TEST] Test 3 passed")
        
        print("\n🎉 [TEST] All tests passed! Override availability is working correctly.")
        
    except Exception as e:
        print(f"\n❌ [TEST] Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_tests()