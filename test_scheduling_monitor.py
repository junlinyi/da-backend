#!/usr/bin/env python3
"""
Test script for the scheduling monitor service
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, time, date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import text
from app.database import get_db
from app.models import (
    User, UserMatchCallPreferences, UserWeeklyAvailability, 
    UserAvailabilityOverride, Match
)
from app.services.scheduling_monitor_service import SchedulingMonitorService

async def test_database_functions():
    """Test the database functions for finding common availability"""
    print("🧪 Testing database functions...")
    
    async for db in get_db():
        try:
            # Get two users for testing
            result = await db.execute(select(User).limit(2))
            users = result.scalars().all()
            
            if len(users) < 2:
                print("❌ Need at least 2 users in database for testing")
                return
            
            user1, user2 = users[0], users[1]
            print(f"✅ Testing with users: {user1.name} and {user2.name}")
            
            # Test the find_common_availability function
            start_date = date.today()
            end_date = start_date + timedelta(days=7)
            
            result = await db.execute(
                text(f"SELECT * FROM find_common_availability({user1.id}, {user2.id}, '{start_date}', '{end_date}')")
            )
            common_slots = result.fetchall()
            
            print(f"✅ Found {len(common_slots)} common availability slots")
            
            # Test the check_scheduling_conflict function
            test_start = datetime.utcnow() + timedelta(hours=1)
            test_end = test_start + timedelta(minutes=15)
            
            result = await db.execute(
                text(f"SELECT check_scheduling_conflict({user1.id}, '{test_start}', '{test_end}')")
            )
            has_conflict = result.scalar()
            
            print(f"✅ Scheduling conflict check: {has_conflict}")
            
        except Exception as e:
            print(f"❌ Error testing database functions: {e}")
        finally:
            await db.close()

async def test_call_preferences():
    """Test call preferences functionality"""
    print("\n🧪 Testing call preferences...")
    
    async for db in get_db():
        try:
            # Get two users for testing
            result = await db.execute(select(User).limit(2))
            users = result.scalars().all()
            
            if len(users) < 2:
                print("❌ Need at least 2 users in database for testing")
                return
            
            user1, user2 = users[0], users[1]
            
            # Check if call preferences exist
            result = await db.execute(
                select(UserMatchCallPreferences).where(
                    UserMatchCallPreferences.user_id == user1.id,
                    UserMatchCallPreferences.matched_user_id == user2.id
                )
            )
            preference = result.scalar_one_or_none()
            
            if preference:
                print(f"✅ Call preference exists: {preference.status}")
            else:
                print("ℹ️  No call preference found (this is normal if no match exists)")
            
            # Count total call preferences
            result = await db.execute(select(UserMatchCallPreferences))
            total_preferences = result.scalars().all()
            print(f"✅ Total call preferences in database: {len(total_preferences)}")
            
        except Exception as e:
            print(f"❌ Error testing call preferences: {e}")
        finally:
            await db.close()

async def test_scheduling_monitor():
    """Test the scheduling monitor service"""
    print("\n🧪 Testing scheduling monitor service...")
    
    try:
        monitor = SchedulingMonitorService()
        
        # Test getting pending matches
        async for db in get_db():
            try:
                result = await db.execute(
                    select(UserMatchCallPreferences)
                    .where(UserMatchCallPreferences.status == 'pending')
                )
                pending_preferences = result.scalars().all()
                
                print(f"✅ Found {len(pending_preferences)} pending call preferences")
                
                if pending_preferences:
                    # Test checking availability for the first preference
                    preference = pending_preferences[0]
                    print(f"✅ Testing availability check for preference {preference.id}")
                    
                    # Get users
                    user1_result = await db.execute(
                        select(User).where(User.id == preference.user_id)
                    )
                    user1 = user1_result.scalar_one_or_none()
                    
                    user2_result = await db.execute(
                        select(User).where(User.id == preference.matched_user_id)
                    )
                    user2 = user2_result.scalar_one_or_none()
                    
                    if user1 and user2:
                        print(f"✅ Users: {user1.name} ↔ {user2.name}")
                        
                        # Test finding common availability
                        start_date = date.today()
                        end_date = start_date + timedelta(days=7)
                        
                        common_slots = await monitor.find_common_availability(
                            db, user1.id, user2.id, start_date, end_date
                        )
                        
                        print(f"✅ Found {len(common_slots)} common availability slots")
                        
                        for i, slot in enumerate(common_slots, 1):
                            print(f"   Slot {i}: {slot['date']} {slot['start_time']}-{slot['end_time']}")
                
            except Exception as e:
                print(f"❌ Error testing scheduling monitor: {e}")
            finally:
                await db.close()
                
    except Exception as e:
        print(f"❌ Error creating scheduling monitor: {e}")

async def test_weekly_availability():
    """Test weekly availability functionality"""
    print("\n🧪 Testing weekly availability...")
    
    async for db in get_db():
        try:
            # Get a user for testing
            result = await db.execute(select(User).limit(1))
            user = result.scalar_one_or_none()
            
            if not user:
                print("❌ Need at least 1 user in database for testing")
                return
            
            # Count existing weekly availability slots
            result = await db.execute(
                select(UserWeeklyAvailability).where(UserWeeklyAvailability.user_id == user.id)
            )
            existing_slots = result.scalars().all()
            
            print(f"✅ User {user.name} has {len(existing_slots)} weekly availability slots")
            
            # Count existing overrides
            result = await db.execute(
                select(UserAvailabilityOverride).where(UserAvailabilityOverride.user_id == user.id)
            )
            existing_overrides = result.scalars().all()
            
            print(f"✅ User {user.name} has {len(existing_overrides)} availability overrides")
            
        except Exception as e:
            print(f"❌ Error testing weekly availability: {e}")
        finally:
            await db.close()

async def main():
    """Run all tests"""
    print("🚀 Starting scheduling system tests...\n")
    
    await test_database_functions()
    await test_call_preferences()
    await test_scheduling_monitor()
    await test_weekly_availability()
    
    print("\n✅ All tests completed!")

if __name__ == "__main__":
    asyncio.run(main()) 