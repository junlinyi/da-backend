"""
Test data generators for When2Meet scheduling system edge cases
Provides comprehensive test datasets for various scenarios
"""

from datetime import datetime, date, time, timedelta
from typing import List, Dict, Any, Tuple
import calendar
from dataclasses import dataclass
from enum import Enum


class TimeSlotPattern(Enum):
    """Predefined patterns for time slot generation"""
    MORNING_PERSON = "morning"  # 6 AM - 12 PM
    NIGHT_OWL = "night"        # 8 PM - 2 AM
    NINE_TO_FIVE = "business"  # 9 AM - 5 PM
    WEEKEND_WARRIOR = "weekend" # Saturday-Sunday only
    FRAGMENTED = "fragmented"   # Random scattered slots
    FULL_WEEK = "full"         # All available slots


@dataclass
class TestUser:
    """Test user data structure"""
    firebase_uid: str
    email: str
    name: str
    timezone: str = "UTC"
    is_active: bool = True


class SchedulingTestDataGenerator:
    """Generates test data for various scheduling scenarios"""
    
    @staticmethod
    def generate_test_users(count: int = 5) -> List[TestUser]:
        """Generate test users with diverse profiles"""
        users = []
        timezones = ["UTC", "America/New_York", "America/Los_Angeles", "Europe/London", "Asia/Tokyo"]
        
        for i in range(count):
            user = TestUser(
                firebase_uid=f"test_user_{i:03d}",
                email=f"test{i}@example.com",
                name=f"Test User {i}",
                timezone=timezones[i % len(timezones)]
            )
            users.append(user)
        
        return users

    @staticmethod
    def generate_week_boundaries() -> List[Tuple[str, str]]:
        """Generate week start dates for boundary testing"""
        boundaries = []
        
        # Year boundaries
        boundaries.extend([
            ("2023-12-31", "New Year transition 2023->2024"),
            ("2024-12-29", "New Year transition 2024->2025"),
            ("2025-12-28", "New Year transition 2025->2026"),
        ])
        
        # Leap year boundaries
        boundaries.extend([
            ("2024-02-25", "Leap year February 2024"),
            ("2024-02-26", "Leap day week 2024"),
            ("2028-02-27", "Leap year February 2028"),
        ])
        
        # Month boundaries
        boundaries.extend([
            ("2024-01-28", "January-February boundary"),
            ("2024-02-25", "February-March boundary"),
            ("2024-04-28", "April-May boundary"),
            ("2024-06-30", "June-July boundary"),
        ])
        
        # DST transitions (US)
        boundaries.extend([
            ("2024-03-10", "Spring DST transition"),
            ("2024-11-03", "Fall DST transition"),
        ])
        
        return boundaries

    @staticmethod
    def generate_time_slots_by_pattern(pattern: TimeSlotPattern, week_start: str = "2024-01-14") -> List[Dict[str, Any]]:
        """Generate time slots based on predefined patterns"""
        slots = []
        
        if pattern == TimeSlotPattern.MORNING_PERSON:
            # Early riser: 6 AM - 12 PM, Monday-Friday
            for day in range(1, 6):  # Monday-Friday
                for hour in range(6, 12):
                    for minute in [0, 30]:
                        slots.append({
                            "day_of_week": day,
                            "hour": hour,
                            "minute": minute,
                            "is_available": True
                        })
        
        elif pattern == TimeSlotPattern.NIGHT_OWL:
            # Night owl: 8 PM - 2 AM, all days
            for day in range(7):
                # Evening slots (8 PM - 11:30 PM)
                for hour in range(20, 24):
                    for minute in [0, 30]:
                        slots.append({
                            "day_of_week": day,
                            "hour": hour,
                            "minute": minute,
                            "is_available": True
                        })
                # Early morning slots (12 AM - 2 AM)
                for hour in range(0, 3):
                    for minute in [0, 30]:
                        slots.append({
                            "day_of_week": day,
                            "hour": hour,
                            "minute": minute,
                            "is_available": True
                        })
        
        elif pattern == TimeSlotPattern.NINE_TO_FIVE:
            # Standard business hours: 9 AM - 5 PM, Monday-Friday
            for day in range(1, 6):  # Monday-Friday
                for hour in range(9, 17):
                    for minute in [0, 30]:
                        slots.append({
                            "day_of_week": day,
                            "hour": hour,
                            "minute": minute,
                            "is_available": True
                        })
        
        elif pattern == TimeSlotPattern.WEEKEND_WARRIOR:
            # Weekend only: Saturday-Sunday, flexible hours
            for day in [0, 6]:  # Sunday, Saturday
                for hour in range(10, 22):  # 10 AM - 10 PM
                    for minute in [0, 30]:
                        slots.append({
                            "day_of_week": day,
                            "hour": hour,
                            "minute": minute,
                            "is_available": True
                        })
        
        elif pattern == TimeSlotPattern.FRAGMENTED:
            # Random scattered availability
            import random
            random.seed(42)  # Deterministic for testing
            
            for day in range(7):
                available_hours = random.sample(range(24), random.randint(3, 8))
                for hour in available_hours:
                    # Randomly choose 0, 30, or both minutes
                    minutes = random.choice([[0], [30], [0, 30]])
                    for minute in minutes:
                        slots.append({
                            "day_of_week": day,
                            "hour": hour,
                            "minute": minute,
                            "is_available": random.choice([True, False])
                        })
        
        elif pattern == TimeSlotPattern.FULL_WEEK:
            # All possible slots
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

    @staticmethod
    def generate_invalid_time_slots() -> List[Dict[str, Any]]:
        """Generate invalid time slots for validation testing"""
        invalid_slots = []
        
        # Invalid day_of_week values
        invalid_slots.extend([
            {"day_of_week": -1, "hour": 9, "minute": 0, "is_available": True},
            {"day_of_week": 7, "hour": 9, "minute": 0, "is_available": True},
            {"day_of_week": 999, "hour": 9, "minute": 0, "is_available": True},
        ])
        
        # Invalid hour values
        invalid_slots.extend([
            {"day_of_week": 1, "hour": -1, "minute": 0, "is_available": True},
            {"day_of_week": 1, "hour": 24, "minute": 0, "is_available": True},
            {"day_of_week": 1, "hour": 999, "minute": 0, "is_available": True},
        ])
        
        # Invalid minute values
        invalid_slots.extend([
            {"day_of_week": 1, "hour": 9, "minute": -1, "is_available": True},
            {"day_of_week": 1, "hour": 9, "minute": 15, "is_available": True},
            {"day_of_week": 1, "hour": 9, "minute": 45, "is_available": True},
            {"day_of_week": 1, "hour": 9, "minute": 60, "is_available": True},
        ])
        
        # Missing required fields
        invalid_slots.extend([
            {"hour": 9, "minute": 0, "is_available": True},  # Missing day_of_week
            {"day_of_week": 1, "minute": 0, "is_available": True},  # Missing hour
            {"day_of_week": 1, "hour": 9, "is_available": True},  # Missing minute
        ])
        
        # Invalid data types
        invalid_slots.extend([
            {"day_of_week": "monday", "hour": 9, "minute": 0, "is_available": True},
            {"day_of_week": 1, "hour": "nine", "minute": 0, "is_available": True},
            {"day_of_week": 1, "hour": 9, "minute": "zero", "is_available": True},
        ])
        
        return invalid_slots

    @staticmethod
    def generate_override_scenarios(user_id: int) -> List[Dict[str, Any]]:
        """Generate override availability scenarios"""
        scenarios = []
        
        # Scenario 1: Early morning meeting
        scenarios.append({
            "user_id": user_id,
            "date": "2024-01-15",  # Monday
            "start_time": "07:00",
            "end_time": "07:30",
            "is_available": True,
            "reason": "Early team standup"
        })
        
        # Scenario 2: Lunch break unavailability
        scenarios.append({
            "user_id": user_id,
            "date": "2024-01-16",  # Tuesday
            "start_time": "12:00",
            "end_time": "13:00",
            "is_available": False,
            "reason": "Lunch break"
        })
        
        # Scenario 3: Late evening availability
        scenarios.append({
            "user_id": user_id,
            "date": "2024-01-17",  # Wednesday
            "start_time": "20:00",
            "end_time": "21:00",
            "is_available": True,
            "reason": "Evening office hours"
        })
        
        # Scenario 4: All-day unavailability
        scenarios.append({
            "user_id": user_id,
            "date": "2024-01-18",  # Thursday
            "start_time": "00:00",
            "end_time": "23:59",
            "is_available": False,
            "reason": "Out of office"
        })
        
        # Scenario 5: Weekend work session
        scenarios.append({
            "user_id": user_id,
            "date": "2024-01-20",  # Saturday
            "start_time": "14:00",
            "end_time": "18:00",
            "is_available": True,
            "reason": "Weekend project work"
        })
        
        return scenarios

    @staticmethod
    def generate_stress_test_data() -> Dict[str, Any]:
        """Generate data for stress/performance testing"""
        data = {}
        
        # Large user set
        data["users"] = SchedulingTestDataGenerator.generate_test_users(100)
        
        # Maximum slots per user (7 days * 24 hours * 2 slots = 336)
        data["max_availability"] = SchedulingTestDataGenerator.generate_time_slots_by_pattern(
            TimeSlotPattern.FULL_WEEK
        )
        
        # Many overrides for a single week
        overrides = []
        for day_offset in range(7):
            for hour in range(8, 18, 2):  # Every 2 hours
                override_date = (datetime(2024, 1, 14) + timedelta(days=day_offset)).date()
                overrides.append({
                    "date": override_date.isoformat(),
                    "start_time": f"{hour:02d}:00",
                    "end_time": f"{hour:02d}:30",
                    "is_available": True,
                    "reason": f"Override {day_offset}-{hour}"
                })
        data["many_overrides"] = overrides
        
        return data

    @staticmethod
    def generate_timezone_test_cases() -> List[Dict[str, Any]]:
        """Generate test cases for timezone handling"""
        test_cases = []
        
        timezones = [
            ("UTC", "Universal Coordinated Time"),
            ("America/New_York", "Eastern Time"),
            ("America/Los_Angeles", "Pacific Time"),
            ("Europe/London", "Greenwich Mean Time"),
            ("Europe/Paris", "Central European Time"),
            ("Asia/Tokyo", "Japan Standard Time"),
            ("Australia/Sydney", "Australian Eastern Time"),
            ("Pacific/Auckland", "New Zealand Time"),
        ]
        
        for tz, description in timezones:
            test_cases.append({
                "timezone": tz,
                "description": description,
                "test_times": [
                    {"hour": 0, "minute": 0, "description": "Midnight"},
                    {"hour": 6, "minute": 0, "description": "Early morning"},
                    {"hour": 12, "minute": 0, "description": "Noon"},
                    {"hour": 18, "minute": 0, "description": "Evening"},
                    {"hour": 23, "minute": 30, "description": "Late night"},
                ]
            })
        
        return test_cases

    @staticmethod
    def generate_conflict_scenarios() -> List[Dict[str, Any]]:
        """Generate scheduling conflict scenarios"""
        conflicts = []
        
        # Scenario 1: Overlapping time slots
        conflicts.append({
            "name": "overlapping_slots",
            "description": "Two users with overlapping availability",
            "user1_slots": [
                {"day_of_week": 1, "hour": 10, "minute": 0, "is_available": True},
                {"day_of_week": 1, "hour": 10, "minute": 30, "is_available": True},
                {"day_of_week": 1, "hour": 11, "minute": 0, "is_available": True},
            ],
            "user2_slots": [
                {"day_of_week": 1, "hour": 10, "minute": 30, "is_available": True},
                {"day_of_week": 1, "hour": 11, "minute": 0, "is_available": True},
                {"day_of_week": 1, "hour": 11, "minute": 30, "is_available": True},
            ],
            "expected_common": [
                {"day_of_week": 1, "hour": 10, "minute": 30},
                {"day_of_week": 1, "hour": 11, "minute": 0},
            ]
        })
        
        # Scenario 2: No common availability
        conflicts.append({
            "name": "no_overlap",
            "description": "Two users with no common availability",
            "user1_slots": [
                {"day_of_week": 1, "hour": 9, "minute": 0, "is_available": True},
                {"day_of_week": 1, "hour": 9, "minute": 30, "is_available": True},
            ],
            "user2_slots": [
                {"day_of_week": 1, "hour": 15, "minute": 0, "is_available": True},
                {"day_of_week": 1, "hour": 15, "minute": 30, "is_available": True},
            ],
            "expected_common": []
        })
        
        # Scenario 3: Complex multi-day overlap
        conflicts.append({
            "name": "multi_day_partial",
            "description": "Complex multi-day availability with partial overlaps",
            "user1_slots": [
                # Monday morning
                {"day_of_week": 1, "hour": 9, "minute": 0, "is_available": True},
                {"day_of_week": 1, "hour": 9, "minute": 30, "is_available": True},
                # Tuesday afternoon
                {"day_of_week": 2, "hour": 14, "minute": 0, "is_available": True},
                {"day_of_week": 2, "hour": 14, "minute": 30, "is_available": True},
                # Friday evening
                {"day_of_week": 5, "hour": 18, "minute": 0, "is_available": True},
            ],
            "user2_slots": [
                # Monday afternoon (no overlap)
                {"day_of_week": 1, "hour": 15, "minute": 0, "is_available": True},
                # Tuesday afternoon (overlap)
                {"day_of_week": 2, "hour": 14, "minute": 0, "is_available": True},
                {"day_of_week": 2, "hour": 14, "minute": 30, "is_available": True},
                {"day_of_week": 2, "hour": 15, "minute": 0, "is_available": True},
                # Friday evening (overlap)
                {"day_of_week": 5, "hour": 18, "minute": 0, "is_available": True},
            ],
            "expected_common": [
                {"day_of_week": 2, "hour": 14, "minute": 0},
                {"day_of_week": 2, "hour": 14, "minute": 30},
                {"day_of_week": 5, "hour": 18, "minute": 0},
            ]
        })
        
        return conflicts

    @staticmethod
    def generate_malformed_request_data() -> List[Dict[str, Any]]:
        """Generate malformed request data for error handling tests"""
        malformed_requests = []
        
        # Missing required fields
        malformed_requests.extend([
            {"time_slots": []},  # Missing user_id
            {"user_id": 123},    # Missing time_slots
            {},                  # Empty request
        ])
        
        # Wrong data types
        malformed_requests.extend([
            {"user_id": "not_an_int", "time_slots": []},
            {"user_id": 123, "time_slots": "not_a_list"},
            {"user_id": None, "time_slots": []},
        ])
        
        # Malformed time slots
        malformed_requests.extend([
            {
                "user_id": 123,
                "time_slots": [
                    "not_a_dict"
                ]
            },
            {
                "user_id": 123,
                "time_slots": [
                    {"invalid": "structure"}
                ]
            },
        ])
        
        return malformed_requests


# Utility functions for test data

def create_test_availability_payload(user_id: int, pattern: TimeSlotPattern, week_start: str = "2024-01-14") -> Dict[str, Any]:
    """Create a complete availability payload for testing"""
    return {
        "user_id": user_id,
        "time_slots": SchedulingTestDataGenerator.generate_time_slots_by_pattern(pattern, week_start)
    }


def create_mixed_availability_payload(user_id: int) -> Dict[str, Any]:
    """Create availability with mix of available and unavailable slots"""
    slots = []
    
    # Monday: Morning available, evening unavailable
    for hour in range(9, 12):  # 9 AM - 12 PM
        for minute in [0, 30]:
            slots.append({
                "day_of_week": 1,
                "hour": hour,
                "minute": minute,
                "is_available": True
            })
    
    for hour in range(18, 20):  # 6 PM - 8 PM
        for minute in [0, 30]:
            slots.append({
                "day_of_week": 1,
                "hour": hour,
                "minute": minute,
                "is_available": False
            })
    
    return {
        "user_id": user_id,
        "time_slots": slots
    }


def create_week_transition_dates() -> List[str]:
    """Create list of week start dates that test various transitions"""
    dates = []
    
    # Generate 52 weeks starting from a Sunday
    start_date = datetime(2024, 1, 7)  # First Sunday of 2024
    for week in range(52):
        week_date = start_date + timedelta(weeks=week)
        dates.append(week_date.strftime("%Y-%m-%d"))
    
    return dates


# Export all generators for easy import
__all__ = [
    'SchedulingTestDataGenerator',
    'TimeSlotPattern', 
    'TestUser',
    'create_test_availability_payload',
    'create_mixed_availability_payload',
    'create_week_transition_dates'
]