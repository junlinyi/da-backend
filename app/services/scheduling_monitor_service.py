"""
Continuous monitoring service for scheduling
Checks for common availability between matched users and sends notifications
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import SessionLocal
from app.models import (
    User, Match, ScheduledCall, BehavioralEvent
)
from app.services import push_notification_service as push
from app.services import match_state_service as mss

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
        self.check_interval = 300  # Slow loop: expire + no-show, every 5 minutes
        self.fast_interval = 60    # Fast loop: text-lock + nudges, every 1 minute
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

    async def check_all_matches(self):
        """Slow loop (every check_interval): V2 expiry + no-show detection.

        Each cron body manages its own per-row error isolation; we commit once
        per tick after both run on a fresh session.
        """
        async for db in get_db_session():
            try:
                await mss.expire_unscheduled_matches(db)
                await mss.detect_no_shows(db)
                await db.commit()
            except Exception as e:
                logger.error(f"[MONITOR] Error in check_all_matches tick: {e}", exc_info=True)
                await db.rollback()
            break

    async def fast_loop(self):
        """Fast loop (every fast_interval=60s): V2 text-lock + pre-lock nudges."""
        logger.info("Starting scheduling monitor FAST loop (text-lock + nudges)")
        while self.is_running:
            async for db in get_db_session():
                try:
                    await mss.lock_text_for_eligible_matches(db)
                    await mss.notify_text_window_nudges(db)
                    await db.commit()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"[MONITOR] Error in fast_loop tick: {e}", exc_info=True)
                    await db.rollback()
                break
            try:
                await asyncio.sleep(self.fast_interval)
            except asyncio.CancelledError:
                logger.info("Scheduling monitor fast_loop received CancelledError — shutting down")
                break

# Global instance
scheduling_monitor = SchedulingMonitorService()

# Background task functions for FastAPI
async def start_scheduling_monitor():
    """Start the scheduling monitor as a background task"""
    await scheduling_monitor.start_monitoring()

async def stop_scheduling_monitor():
    """Stop the scheduling monitor"""
    await scheduling_monitor.stop_monitoring()


async def start_fast_monitor():
    """Start the 60s text-lock + nudge loop as a background task."""
    # The fast loop and slow loop share `is_running`; ensure it's set so the
    # fast loop runs even if started before/independently of the slow loop.
    scheduling_monitor.is_running = True
    await scheduling_monitor.fast_loop()
