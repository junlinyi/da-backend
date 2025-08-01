#!/usr/bin/env python3
"""
Test script for all scheduling endpoints
This script tests all scheduling functionality with the restored database
"""

import asyncio
import aiohttp
import json
from datetime import datetime, time, date, timedelta
import pytz

# Test configuration
BASE_URL = "http://localhost:8000"
TEST_USER_FIREBASE_UID = "ITnBfONkfab6UUCxr2CwXeLdA8A2"  # Use one of the existing users

# Mock Firebase token for testing (in real app, this would be a valid Firebase token)
MOCK_TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOiJJVG5CZk9Oa2ZhYjZVVUN4cjJDd1hlTGRBOEEyIiwiaWF0IjoxNjM5NzI5NjAwLCJleHAiOjE2Mzk4MTYwMDB9.test"

async def make_request(session, method, endpoint, data=None, headers=None):
    """Make HTTP request with proper headers"""
    if headers is None:
        headers = {}
    
    headers.update({
        "Authorization": f"Bearer {MOCK_TOKEN}",
        "Content-Type": "application/json"
    })
    
    url = f"{BASE_URL}{endpoint}"
    
    try:
        if method.upper() == "GET":
            async with session.get(url, headers=headers) as response:
                return response.status, await response.text()
        elif method.upper() == "POST":
            async with session.post(url, headers=headers, json=data) as response:
                return response.status, await response.text()
        elif method.upper() == "PUT":
            async with session.put(url, headers=headers, json=data) as response:
                return response.status, await response.text()
        elif method.upper() == "DELETE":
            async with session.delete(url, headers=headers) as response:
                return response.status, await response.text()
    except Exception as e:
        return 500, f"Request failed: {str(e)}"

async def test_weekly_availability(session):
    """Test weekly availability endpoints"""
    print("\n=== Testing Weekly Availability Endpoints ===")
    
    # Test GET weekly availability
    status, response = await make_request(session, "GET", "/scheduling/me/availability/weekly")
    print(f"GET /scheduling/me/availability/weekly: {status}")
    if status == 200:
        data = json.loads(response)
        print(f"  Found {len(data)} weekly availability slots")
    
    # Test POST weekly availability
    new_availability = {
        "day_of_week": 1,  # Monday
        "start_time": "18:00:00",
        "end_time": "19:00:00"
    }
    status, response = await make_request(session, "POST", "/scheduling/me/availability/weekly", new_availability)
    print(f"POST /scheduling/me/availability/weekly: {status}")
    if status == 200:
        data = json.loads(response)
        availability_id = data.get("id")
        print(f"  Created availability slot ID: {availability_id}")
        
        # Test PUT weekly availability
        updated_availability = {
            "day_of_week": 1,
            "start_time": "19:00:00",
            "end_time": "20:00:00"
        }
        status, response = await make_request(session, "PUT", f"/scheduling/me/availability/weekly/{availability_id}", updated_availability)
        print(f"PUT /scheduling/me/availability/weekly/{availability_id}: {status}")
        
        # Test DELETE weekly availability
        status, response = await make_request(session, "DELETE", f"/scheduling/me/availability/weekly/{availability_id}")
        print(f"DELETE /scheduling/me/availability/weekly/{availability_id}: {status}")

async def test_availability_overrides(session):
    """Test availability override endpoints"""
    print("\n=== Testing Availability Override Endpoints ===")
    
    # Test GET overrides
    status, response = await make_request(session, "GET", "/scheduling/me/availability/overrides")
    print(f"GET /scheduling/me/availability/overrides: {status}")
    if status == 200:
        data = json.loads(response)
        print(f"  Found {len(data)} availability overrides")
    
    # Test POST override
    tomorrow = date.today() + timedelta(days=1)
    new_override = {
        "date": tomorrow.isoformat(),
        "start_time": "20:00:00",
        "end_time": "21:00:00",
        "reason": "Test override"
    }
    status, response = await make_request(session, "POST", "/scheduling/me/availability/overrides", new_override)
    print(f"POST /scheduling/me/availability/overrides: {status}")
    if status == 200:
        data = json.loads(response)
        override_id = data.get("id")
        print(f"  Created override ID: {override_id}")
        
        # Test PUT override
        updated_override = {
            "date": tomorrow.isoformat(),
            "start_time": "21:00:00",
            "end_time": "22:00:00",
            "reason": "Updated test override"
        }
        status, response = await make_request(session, "PUT", f"/scheduling/me/availability/overrides/{override_id}", updated_override)
        print(f"PUT /scheduling/me/availability/overrides/{override_id}: {status}")
        
        # Test DELETE override
        status, response = await make_request(session, "DELETE", f"/scheduling/me/availability/overrides/{override_id}")
        print(f"DELETE /scheduling/me/availability/overrides/{override_id}: {status}")

async def test_timezone_endpoints(session):
    """Test timezone endpoints"""
    print("\n=== Testing Timezone Endpoints ===")
    
    # Test GET timezone
    status, response = await make_request(session, "GET", "/scheduling/me/timezone")
    print(f"GET /scheduling/me/timezone: {status}")
    if status == 200:
        data = json.loads(response)
        print(f"  Current timezone: {data.get('timezone', 'Not set')}")
    
    # Test PUT timezone
    timezone_data = {
        "timezone": "America/New_York",
        "timezone_offset": -300,  # -5 hours in minutes
        "dst_enabled": True
    }
    status, response = await make_request(session, "PUT", "/scheduling/me/timezone", timezone_data)
    print(f"PUT /scheduling/me/timezone: {status}")
    if status == 200:
        data = json.loads(response)
        print(f"  Updated timezone to: {data.get('timezone')}")

async def test_scheduling_preferences(session):
    """Test scheduling preferences endpoints"""
    print("\n=== Testing Scheduling Preferences Endpoints ===")
    
    # Test GET preferences
    status, response = await make_request(session, "GET", "/scheduling/me/preferences")
    print(f"GET /scheduling/me/preferences: {status}")
    if status == 200:
        data = json.loads(response)
        print(f"  Max calls per week: {data.get('max_calls_per_week')}")
    
    # Test PUT preferences
    preferences_data = {
        "max_calls_per_week": 3,
        "min_notice_hours": 4,
        "max_advance_days": 14,
        "preferred_start_time": "19:00:00",
        "preferred_end_time": "21:00:00",
        "email_notifications": True,
        "push_notifications": False,
        "reminder_hours_before": 2
    }
    status, response = await make_request(session, "PUT", "/scheduling/me/preferences", preferences_data)
    print(f"PUT /scheduling/me/preferences: {status}")
    if status == 200:
        data = json.loads(response)
        print(f"  Updated max calls per week to: {data.get('max_calls_per_week')}")

async def test_calls_endpoints(session):
    """Test video call endpoints"""
    print("\n=== Testing Video Call Endpoints ===")
    
    # Test GET my calls
    status, response = await make_request(session, "GET", "/scheduling/me/calls")
    print(f"GET /scheduling/me/calls: {status}")
    if status == 200:
        data = json.loads(response)
        print(f"  Found {len(data)} calls")
    
    # Test GET my calls with filters
    status, response = await make_request(session, "GET", "/scheduling/me/calls?upcoming=true&status=scheduled")
    print(f"GET /scheduling/me/calls?upcoming=true&status=scheduled: {status}")
    
    # Note: POST /scheduling/calls requires a valid match_id, so we'll skip that for now
    print("  POST /scheduling/calls: Skipped (requires valid match_id)")

async def test_availability_checking(session):
    """Test availability checking endpoints"""
    print("\n=== Testing Availability Checking Endpoints ===")
    
    # Test availability check
    check_request = {
        "user_id": 1,
        "start_time_utc": (datetime.utcnow() + timedelta(days=1)).isoformat(),
        "end_time_utc": (datetime.utcnow() + timedelta(days=1, hours=1)).isoformat()
    }
    status, response = await make_request(session, "POST", "/scheduling/availability/check", check_request)
    print(f"POST /scheduling/availability/check: {status}")
    if status == 200:
        data = json.loads(response)
        print(f"  User available: {data.get('is_available')}")
    
    # Test common availability
    common_request = {
        "user1_id": 1,
        "user2_id": 2,
        "start_date": date.today().isoformat(),
        "end_date": (date.today() + timedelta(days=7)).isoformat()
    }
    status, response = await make_request(session, "POST", "/scheduling/availability/common", common_request)
    print(f"POST /scheduling/availability/common: {status}")
    if status == 200:
        data = json.loads(response)
        print(f"  Found {len(data.get('available_slots', []))} common slots")

async def test_complete_schedule(session):
    """Test complete schedule endpoint"""
    print("\n=== Testing Complete Schedule Endpoint ===")
    
    status, response = await make_request(session, "GET", "/scheduling/me/schedule")
    print(f"GET /scheduling/me/schedule: {status}")
    if status == 200:
        data = json.loads(response)
        print(f"  User ID: {data.get('user_id')}")
        print(f"  Weekly availability slots: {len(data.get('weekly_availability', []))}")
        print(f"  Overrides: {len(data.get('overrides', []))}")
        print(f"  Upcoming calls: {len(data.get('upcoming_calls', []))}")
        print(f"  Past calls: {len(data.get('past_calls', []))}")
        print(f"  Has timezone: {data.get('timezone') is not None}")
        print(f"  Has preferences: {data.get('preferences') is not None}")

async def test_database_connection():
    """Test database connection and table access"""
    print("\n=== Testing Database Connection ===")
    
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            user="dating_user",
            password="dating_password",
            database="dating_app"
        )
        cursor = conn.cursor()
        
        # Test table access
        tables = [
            "users", "matches", "conversations", "messages", "swipes",
            "user_weekly_availability", "user_availability_overrides",
            "user_timezones", "user_scheduling_preferences",
            "scheduled_calls", "call_ratings"
        ]
        
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"  {table}: {count} records")
        
        cursor.close()
        conn.close()
        print("  Database connection: ✅ Success")
        
    except Exception as e:
        print(f"  Database connection: ❌ Failed - {str(e)}")

async def main():
    """Run all tests"""
    print("🚀 Starting Scheduling Endpoints Test Suite")
    print("=" * 50)
    
    # Test database connection first
    await test_database_connection()
    
    # Test all scheduling endpoints
    async with aiohttp.ClientSession() as session:
        await test_weekly_availability(session)
        await test_availability_overrides(session)
        await test_timezone_endpoints(session)
        await test_scheduling_preferences(session)
        await test_calls_endpoints(session)
        await test_availability_checking(session)
        await test_complete_schedule(session)
    
    print("\n" + "=" * 50)
    print("✅ Scheduling Endpoints Test Suite Complete!")
    print("\nNote: Some endpoints may return 401 (Unauthorized) because we're using a mock token.")
    print("In a real app, you would use a valid Firebase authentication token.")

if __name__ == "__main__":
    asyncio.run(main()) 