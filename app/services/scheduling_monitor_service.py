"""
Continuous monitoring service for scheduling
Checks for common availability between matched users and sends notifications
"""

import asyncio
import logging
from datetime import datetime, timedelta, date, timezone
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import and_, or_
import pytz

from app.database import SessionLocal
from app.models import (
    User, Match, UserMatchCallPreferences, UserWeeklyAvailability, 
    UserAvailabilityOverride, ScheduledCall, UserTimezone
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def utc_now() -> datetime:
    """Get current UTC time as timezone-aware datetime object"""
    return datetime.now(timezone.utc)

async def get_db_session():
    """Get a database session for background services"""
    async with SessionLocal() as session:
        yield session

# Placeholder function for push notifications (to be implemented later)
async def send_push_notification(firebase_uid: str, title: str, message: str, data: dict = None):
    """Placeholder function for sending push notifications"""
    logger.info(f"Would send push notification to {firebase_uid}: {title} - {message}")
    # TODO: Implement actual push notification logic
    pass

class SchedulingMonitorService:
    """
    Continuous monitoring service for scheduling
    
    This service:
    1. Monitors user-match pairs for common availability
    2. Sends notifications when common slots are found
    3. Prevents duplicate notifications
    4. Handles user preferences (wants to call, doesn't want to call, etc.)
    """
    
    def __init__(self):
        self.is_running = False
        self.check_interval = 300  # Check every 5 minutes
        self.notification_cooldown = 3600  # Don't send notifications more than once per hour
        
    async def start_monitoring(self):
        """Start the continuous monitoring service"""
        if self.is_running:
            logger.warning("Scheduling monitor is already running")
            return
        
        self.is_running = True
        logger.info("Starting scheduling monitor service")
        
        try:
            while self.is_running:
                await self.check_all_matches()
                await asyncio.sleep(self.check_interval)
        except Exception as e:
            logger.error(f"Error in scheduling monitor: {e}")
            self.is_running = False
            raise
    
    async def stop_monitoring(self):
        """Stop the continuous monitoring service"""
        self.is_running = False
        logger.info("Stopping scheduling monitor service")
    
    async def check_all_matches(self):
        """Check all pending matches for common availability"""
        async for db in get_db_session():
            try:
                # Get all pending call preferences
                result = await db.execute(
                    select(UserMatchCallPreferences)
                    .where(UserMatchCallPreferences.status == 'pending')
                )
                pending_preferences = result.scalars().all()
                
                logger.info(f"Checking {len(pending_preferences)} pending call preferences")
                
                for preference in pending_preferences:
                    # Additional safety check: ensure no scheduled calls exist
                    scheduled_call_result = await db.execute(
                        select(ScheduledCall).where(
                            and_(
                                or_(
                                    and_(ScheduledCall.user1_id == preference.user_id, 
                                         ScheduledCall.user2_id == preference.matched_user_id),
                                    and_(ScheduledCall.user1_id == preference.matched_user_id, 
                                         ScheduledCall.user2_id == preference.user_id)
                                ),
                                ScheduledCall.status.in_(['scheduled', 'in_progress'])
                            )
                        )
                    )
                    existing_call = scheduled_call_result.scalar_one_or_none()
                    
                    if existing_call:
                        logger.info(f"Skipping preference {preference.id}: call already scheduled for {existing_call.id}")
                        # Update status to prevent future checks
                        preference.status = 'wants_to_call'
                        await db.commit()
                        continue
                    
                    await self.check_match_availability(db, preference)
                    
            except Exception as e:
                logger.error(f"Error checking matches: {e}")
                await db.rollback()
                break
    
    async def check_match_availability(self, db: AsyncSession, preference: UserMatchCallPreferences):
        """Check availability for a specific user-match pair"""
        try:
            # Get both users
            user1_result = await db.execute(
                select(User).where(User.id == preference.user_id)
            )
            user1 = user1_result.scalar_one_or_none()
            
            user2_result = await db.execute(
                select(User).where(User.id == preference.matched_user_id)
            )
            user2 = user2_result.scalar_one_or_none()
            
            if not user1 or not user2:
                logger.warning(f"User not found for preference {preference.id}")
                return
            
            # Check if we should skip this check (cooldown period)
            if preference.last_common_availability_check:
                time_since_last_check = utc_now() - preference.last_common_availability_check
                if time_since_last_check.total_seconds() < self.check_interval:
                    return
            
            # Find common availability for next 7 days
            start_date = date.today()
            end_date = start_date + timedelta(days=7)
            
            common_slots = await self.find_common_availability(
                db, user1.id, user2.id, start_date, end_date
            )
            
            # Update last check time
            preference.last_common_availability_check = utc_now()
            await db.commit()
            
            if common_slots:
                # Check if we should send notification (cooldown)
                should_send = True
                if preference.last_notification_sent:
                    time_since_notification = utc_now() - preference.last_notification_sent
                    if time_since_notification.total_seconds() < self.notification_cooldown:
                        should_send = False
                
                if should_send:
                    await self.send_availability_notification(db, user1, user2, common_slots)
                    preference.last_notification_sent = utc_now()
                    await db.commit()
                    
                    logger.info(f"Sent availability notification to users {user1.id} and {user2.id}")
            
        except Exception as e:
            logger.error(f"Error checking availability for preference {preference.id}: {e}")
    
    async def find_common_availability(
        self, 
        db: AsyncSession, 
        user1_id: int, 
        user2_id: int, 
        start_date: date, 
        end_date: date
    ) -> List[dict]:
        """Find common availability between two users"""
        try:
            # Use the database function to find common availability
            from sqlalchemy import text
            result = await db.execute(
                text(f"SELECT * FROM find_common_availability({user1_id}, {user2_id}, '{start_date}', '{end_date}')")
            )
            common_slots = result.fetchall()
            
            # Convert to response format and filter out past times
            available_slots = []
            now = utc_now()
            
            for slot in common_slots:
                # Convert date and time to UTC datetime (timezone-aware)
                slot_start_utc = datetime.combine(slot.date, slot.start_time, timezone.utc)
                slot_end_utc = datetime.combine(slot.date, slot.end_time, timezone.utc)
                
                # Only include future slots
                if slot_start_utc > now:
                    available_slots.append({
                        "start_time_utc": slot_start_utc,
                        "end_time_utc": slot_end_utc,
                        "date": slot.date,
                        "start_time": slot.start_time,
                        "end_time": slot.end_time
                    })
            
            # Sort by start time and take earliest 3
            available_slots.sort(key=lambda x: x["start_time_utc"])
            return available_slots[:3]
            
        except Exception as e:
            logger.error(f"Error finding common availability: {e}")
            return []
    
    async def send_availability_notification(
        self, 
        db: AsyncSession, 
        user1: User, 
        user2: User, 
        common_slots: List[dict]
    ):
        """Send push notification to both users about common availability"""
        try:
            # Format the notification message
            if len(common_slots) == 1:
                slot = common_slots[0]
                message = f"You and {user2.name} are both free on {slot['date'].strftime('%A, %B %d')} at {slot['start_time'].strftime('%I:%M %p')}. Schedule your call now!"
            else:
                message = f"You and {user2.name} have {len(common_slots)} time slots in common this week. Schedule your call now!"
            
            # Send to user1
            await send_push_notification(
                user1.firebase_uid,
                "Schedule Your Call! 📞",
                message,
                {
                    "type": "scheduling_availability",
                    "matched_user_id": user2.id,
                    "matched_user_name": user2.name,
                    "available_slots": len(common_slots)
                }
            )
            
            # Send to user2
            await send_push_notification(
                user2.firebase_uid,
                "Schedule Your Call! 📞",
                message,
                {
                    "type": "scheduling_availability",
                    "matched_user_id": user1.id,
                    "matched_user_name": user1.name,
                    "available_slots": len(common_slots)
                }
            )
            
        except Exception as e:
            logger.error(f"Error sending availability notification: {e}")
    
    async def update_call_preference(
        self, 
        user_id: int, 
        matched_user_id: int, 
        status: str
    ):
        """Update call preference for a user-match pair"""
        async for db in get_db_session():
            try:
                result = await db.execute(
                    select(UserMatchCallPreferences).where(
                        UserMatchCallPreferences.user_id == user_id,
                        UserMatchCallPreferences.matched_user_id == matched_user_id
                    )
                )
                preference = result.scalar_one_or_none()
                
                if preference:
                    preference.status = status
                    preference.updated_at = utc_now()
                else:
                    # Create new preference
                    preference = UserMatchCallPreferences(
                        user_id=user_id,
                        matched_user_id=matched_user_id,
                        status=status
                    )
                    db.add(preference)
                
                await db.commit()
                logger.info(f"Updated call preference for user {user_id} with {matched_user_id}: {status}")
                
            except Exception as e:
                logger.error(f"Error updating call preference: {e}")
            finally:
                await db.close()
    
    async def get_pending_matches_for_user(self, user_id: int) -> List[dict]:
        """Get all pending matches for a user that want to call"""
        async for db in get_db_session():
            try:
                result = await db.execute(
                    select(UserMatchCallPreferences)
                    .where(
                        UserMatchCallPreferences.user_id == user_id,
                        UserMatchCallPreferences.status == 'wants_to_call'
                    )
                )
                preferences = result.scalars().all()
                
                matches = []
                for pref in preferences:
                    # Get the matched user
                    matched_user_result = await db.execute(
                        select(User).where(User.id == pref.matched_user_id)
                    )
                    matched_user = matched_user_result.scalar_one_or_none()
                    
                    if matched_user:
                        matches.append({
                            "matched_user_id": matched_user.id,
                            "matched_user_name": matched_user.name,
                            "matched_user_profile_image": matched_user.profile_image_url,
                            "preference_created_at": pref.created_at,
                            "last_availability_check": pref.last_common_availability_check
                        })
                
                return matches
                
            except Exception as e:
                logger.error(f"Error getting pending matches: {e}")
                return []
            finally:
                await db.close()

# Global instance
scheduling_monitor = SchedulingMonitorService()

# Background task functions for FastAPI
async def start_scheduling_monitor():
    """Start the scheduling monitor as a background task"""
    await scheduling_monitor.start_monitoring()

async def stop_scheduling_monitor():
    """Stop the scheduling monitor"""
    await scheduling_monitor.stop_monitoring() 