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
    UserAvailabilityOverride, ScheduledCall, UserTimezone, BehavioralEvent
)
from app.services import push_notification_service as push

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

        while self.is_running:
            try:
                await self.check_all_matches()
            except asyncio.CancelledError:
                logger.info("Scheduling monitor received CancelledError — shutting down")
                break
            except Exception as e:
                logger.error(
                    f"[MONITOR] Uncaught error in check_all_matches — will retry in {self.check_interval}s: {e}",
                    exc_info=True,
                )
            await asyncio.sleep(self.check_interval)
    
    async def stop_monitoring(self):
        """Stop the continuous monitoring service"""
        self.is_running = False
        logger.info("Stopping scheduling monitor service")
    
    async def expire_stale_matches(self, db: AsyncSession) -> int:
        """Mark active matches as expired if past the 48-hour scheduling window with no call.

        Returns the number of matches expired.
        """
        from app.models import MatchOutcome
        now = utc_now()
        cutoff = now - timedelta(hours=48)

        # Find active matches older than 48 hours
        stale_q = await db.execute(
            select(Match).where(
                Match.status.in_(["active", "accepted", "pending"]),
                Match.created_at < cutoff,
            )
        )
        stale_matches = stale_q.scalars().all()

        expired_count = 0
        for match in stale_matches:
            # Skip if a completed/scheduled call exists for this match
            call_q = await db.execute(
                select(ScheduledCall).where(
                    ScheduledCall.match_id == match.id,
                    ScheduledCall.status.in_(["scheduled", "in_progress", "completed"]),
                ).limit(1)
            )
            if call_q.scalars().first():
                continue

            match.status = "expired"
            expired_count += 1

        if expired_count:
            await db.commit()
            logger.info(f"[EXPIRY] Expired {expired_count} stale matches past 48-hour window")

        return expired_count

    async def notify_expiring_matches(self, db: AsyncSession) -> int:
        """S7 — Notify both users when a match's 48h window has ≤6 hours left.

        Uses the last_notification_sent cooldown to avoid re-sending within an hour.
        Returns the number of notifications sent.
        """
        now = utc_now()
        warning_cutoff = now - timedelta(hours=42)   # 42h elapsed → 6h remaining
        expiry_cutoff = now - timedelta(hours=48)    # already expired

        # Matches in the warning window: created between 42h and 48h ago
        expiring_q = await db.execute(
            select(Match).where(
                Match.status.in_(["active", "accepted", "pending"]),
                Match.created_at < warning_cutoff,
                Match.created_at >= expiry_cutoff,
            )
        )
        expiring_matches = expiring_q.scalars().all()

        sent = 0
        for match in expiring_matches:
            # Skip if a call is already scheduled
            call_q = await db.execute(
                select(ScheduledCall).where(
                    ScheduledCall.match_id == match.id,
                    ScheduledCall.status.in_(["scheduled", "in_progress", "completed"]),
                ).limit(1)
            )
            if call_q.scalars().first():
                continue

            # Load both users
            u1_q = await db.execute(select(User).where(User.id == match.user_id))
            u1 = u1_q.scalar_one_or_none()
            u2_q = await db.execute(select(User).where(User.id == match.matched_user_id))
            u2 = u2_q.scalar_one_or_none()
            if not u1 or not u2:
                continue

            hours_left = max(0, int((match.created_at + timedelta(hours=48) - now).total_seconds() // 3600))

            for user in (u1, u2):
                try:
                    other = u2 if user.id == u1.id else u1
                    await push.notify_match_expiring(
                        user=user,
                        match_name=other.name or "your match",
                        hours_left=hours_left,
                    )
                    sent += 1
                except Exception as exc:
                    logger.warning(f"[PUSH] S7 notification failed for user {user.id}: {exc}")

        if sent:
            logger.info(f"[EXPIRY_WARN] Sent {sent} match-expiry warning notifications")
        return sent

    async def detect_no_shows(self, db: AsyncSession) -> int:
        """Mark scheduled calls as no_show when start_time + 20 min has passed and nobody joined.

        Increments no_show_count on absent users and notifies the waiting partner.
        Returns the number of calls marked as no_show.
        """
        now = utc_now()
        no_show_cutoff = now - timedelta(minutes=20)

        # Calls that started more than 20 minutes ago and are still in 'scheduled' state
        stale_q = await db.execute(
            select(ScheduledCall).where(
                ScheduledCall.status == "scheduled",
                ScheduledCall.scheduled_start_utc < no_show_cutoff,
            )
        )
        stale_calls = stale_q.scalars().all()

        count = 0
        for call in stale_calls:
            call.status = "no_show"
            call.cancellation_reason = "no_show"
            call.call_ended_at = now

            # Load both participants
            u1_q = await db.execute(select(User).where(User.id == call.user1_id))
            u1 = u1_q.scalar_one_or_none()
            u2_q = await db.execute(select(User).where(User.id == call.user2_id))
            u2 = u2_q.scalar_one_or_none()

            joined_ids: set[int] = set()
            if call.call_started_at:
                # If the call started at all, at least one user joined — treat both as present.
                # Granular per-participant tracking requires Twilio webhook data; skip for now.
                joined_ids = {call.user1_id, call.user2_id}

            for user in (u for u in [u1, u2] if u is not None):
                if user.id not in joined_ids:
                    # Increment no_show counter on absent user
                    user.no_show_count = (user.no_show_count or 0) + 1
                    user.last_no_show_at = now

                    # Log a behavioral event for the ML system
                    db.add(BehavioralEvent(
                        user_id=user.id,
                        event_type="call_no_show",
                        event_meta={"call_id": call.id, "match_id": call.match_id},
                    ))

            # Notify the waiting user (the one who joined when the other didn't)
            if u1 and u2 and not joined_ids:
                # Neither joined — notify both that the call didn't happen
                for waiting, absent in [(u1, u2), (u2, u1)]:
                    try:
                        await push.notify_no_show_partner(
                            waiting_user=waiting,
                            absent_name=absent.name or "Your match",
                            call_id=call.id,
                        )
                    except Exception as exc:
                        logger.warning(f"[NO_SHOW] Push failed for user {waiting.id}: {exc}")

            count += 1

        if count:
            await db.commit()
            logger.info(f"[NO_SHOW] Marked {count} call(s) as no_show")

        return count

    async def check_all_matches(self):
        """Check all pending matches for common availability and expire stale ones."""
        async for db in get_db_session():
            try:
                # Expire matches that have passed the 48h scheduling window
                await self.expire_stale_matches(db)

                # Mark calls that were never joined as no_show
                await self.detect_no_shows(db)

                # S7 — warn users whose match window is almost closed
                await self.notify_expiring_matches(db)

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
                        ).limit(1)
                    )
                    existing_call = scheduled_call_result.scalars().first()

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
            # Use the database function to find common availability.
            # Run inside a savepoint so a failure doesn't abort the outer transaction.
            from sqlalchemy import text
            async with db.begin_nested():
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
        """S8 — notify both users when common availability is found."""
        try:
            await push.notify_availability_match(user1, user2, slot_count=len(common_slots))
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