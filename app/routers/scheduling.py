# app/routers/scheduling.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime, time, date, timedelta, timezone
import pytz
from app.database import get_db
from app.models import (
    User, UserWeeklyAvailability, UserAvailabilityOverride,
    UserTimezone, UserSchedulingPreferences, ScheduledCall, Match,
    UserMatchCallPreferences, SchedulingProposal, ProposalTimeSlot,
    ProposalResponse, CounterProposalTimeSlot, MatchOutcome
)
from app.schemas import (
    UserWeeklyAvailabilityCreate, UserWeeklyAvailabilityResponse,
    UserAvailabilityOverrideCreate, UserAvailabilityOverrideResponse,
    UserTimezoneCreate, UserTimezoneResponse,
    UserSchedulingPreferenceCreate, UserSchedulingPreferenceResponse,
    ScheduledCallCreate, ScheduledCallResponse,
    AvailabilityCheckRequest, AvailabilityCheckResponse,
    FindCommonAvailabilityRequest, FindCommonAvailabilityResponse,
    AvailabilityResponse, UserScheduleResponse,
    # New batch schemas
    WeeklyAvailabilityBatchCreate, WeeklyAvailabilityBatchResponse,
    AvailabilityOverrideBatchCreate, AvailabilityOverrideBatchResponse,
    CallPreferenceUpdate, CallPreferenceResponse,
    # Proposal system schemas
    SchedulingProposalCreate, SchedulingProposalResponse, ProposalResponseCreate,
    ProposalResponseResponse, ProposalListResponse, ScheduledCallFromProposal,
    ProposalStatus, ProposalResponseType
)
from app.dependencies import verify_firebase_token, get_current_user
import logging
import traceback
import firebase_admin
from firebase_admin import auth as firebase_auth
from app.services import push_notification_service as push

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure Firebase Admin is initialized
if not firebase_admin._apps:
    firebase_admin.initialize_app()

router = APIRouter()


# ============================================================================
# WEEKLY AVAILABILITY ENDPOINTS
# ============================================================================

@router.get("/me/availability/weekly", response_model=List[UserWeeklyAvailabilityResponse])
async def get_weekly_availability(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's weekly availability slots"""
    result = await db.execute(
        select(UserWeeklyAvailability)
        .where(UserWeeklyAvailability.user_id == user.id)
        .order_by(UserWeeklyAvailability.day_of_week, UserWeeklyAvailability.start_time)
    )
    return result.scalars().all()

@router.post("/me/availability/weekly", response_model=UserWeeklyAvailabilityResponse)
async def create_weekly_availability(
    availability: UserWeeklyAvailabilityCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new weekly availability slot"""
    # Check for conflicts
    existing = await db.execute(
        select(UserWeeklyAvailability)
        .where(
            UserWeeklyAvailability.user_id == user.id,
            UserWeeklyAvailability.day_of_week == availability.day_of_week,
            UserWeeklyAvailability.start_time == availability.start_time,
            UserWeeklyAvailability.end_time == availability.end_time
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Availability slot already exists")
    
    new_availability = UserWeeklyAvailability(
        user_id=user.id,
        day_of_week=availability.day_of_week,
        start_time=availability.start_time,
        end_time=availability.end_time
    )
    db.add(new_availability)
    await db.commit()
    await db.refresh(new_availability)
    
    logger.info(f"Created weekly availability for user {user.id}")
    return new_availability

# NEW: Batch endpoints for weekly availability
@router.post("/me/availability/weekly/batch", response_model=WeeklyAvailabilityBatchResponse)
async def create_weekly_availability_batch(
    batch_data: WeeklyAvailabilityBatchCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create multiple weekly availability slots at once (When2Meet style)"""
    created_slots = []
    errors = []
    
    for slot in batch_data.slots:
        try:
            # Check for conflicts
            existing = await db.execute(
                select(UserWeeklyAvailability)
                .where(
                    UserWeeklyAvailability.user_id == user.id,
                    UserWeeklyAvailability.day_of_week == slot.day_of_week,
                    UserWeeklyAvailability.start_time == slot.start_time,
                    UserWeeklyAvailability.end_time == slot.end_time
                )
            )
            if existing.scalars().first():
                errors.append(f"Slot already exists: {slot.day_of_week} {slot.start_time}-{slot.end_time}")
                continue
            
            new_availability = UserWeeklyAvailability(
                user_id=user.id,
                day_of_week=slot.day_of_week,
                start_time=slot.start_time,
                end_time=slot.end_time
            )
            db.add(new_availability)
            created_slots.append(new_availability)
            
        except Exception as e:
            errors.append(f"Error creating slot {slot.day_of_week} {slot.start_time}-{slot.end_time}: {str(e)}")
    
    if created_slots:
        await db.commit()
        for slot in created_slots:
            await db.refresh(slot)
    
    logger.info(f"Created {len(created_slots)} weekly availability slots for user {user.id}")
    return WeeklyAvailabilityBatchResponse(
        created_slots=created_slots,
        errors=errors,
        total_created=len(created_slots),
        total_errors=len(errors)
    )

@router.delete("/me/availability/weekly/batch")
async def delete_weekly_availability_batch(
    day_of_week: Optional[int] = Query(None, description="Delete all slots for specific day (0-6)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete all weekly availability slots for a specific day (When2Meet style clear)"""
    query = select(UserWeeklyAvailability).where(UserWeeklyAvailability.user_id == user.id)
    
    if day_of_week is not None:
        query = query.where(UserWeeklyAvailability.day_of_week == day_of_week)
    
    result = await db.execute(query)
    slots_to_delete = result.scalars().all()
    
    for slot in slots_to_delete:
        await db.delete(slot)
    
    await db.commit()
    
    logger.info(f"Deleted {len(slots_to_delete)} weekly availability slots for user {user.id}")
    return {"message": f"Deleted {len(slots_to_delete)} availability slots"}

@router.put("/me/availability/weekly/{availability_id}", response_model=UserWeeklyAvailabilityResponse)
async def update_weekly_availability(
    availability_id: int,
    availability: UserWeeklyAvailabilityCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a weekly availability slot"""
    result = await db.execute(
        select(UserWeeklyAvailability)
        .where(
            UserWeeklyAvailability.id == availability_id,
            UserWeeklyAvailability.user_id == user.id
        )
    )
    existing = result.scalars().first()
    
    if not existing:
        raise HTTPException(status_code=404, detail="Availability slot not found")
    
    # Update fields
    existing.day_of_week = availability.day_of_week
    existing.start_time = availability.start_time
    existing.end_time = availability.end_time
    
    await db.commit()
    await db.refresh(existing)
    
    logger.info(f"Updated weekly availability {availability_id} for user {user.id}")
    return existing

@router.delete("/me/availability/weekly/{availability_id}")
async def delete_weekly_availability(
    availability_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a weekly availability slot"""
    result = await db.execute(
        select(UserWeeklyAvailability)
        .where(
            UserWeeklyAvailability.id == availability_id,
            UserWeeklyAvailability.user_id == user.id
        )
    )
    existing = result.scalars().first()
    
    if not existing:
        raise HTTPException(status_code=404, detail="Availability slot not found")
    
    await db.delete(existing)
    await db.commit()
    
    logger.info(f"Deleted weekly availability {availability_id} for user {user.id}")
    return {"message": "Availability slot deleted successfully"}

# ============================================================================
# AVAILABILITY OVERRIDE ENDPOINTS
# ============================================================================

@router.get("/me/availability/overrides", response_model=List[UserAvailabilityOverrideResponse])
async def get_availability_overrides(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    start_date: Optional[date] = Query(None, description="Filter overrides from this date"),
    end_date: Optional[date] = Query(None, description="Filter overrides until this date")
):
    """Get user's availability overrides"""
    query = select(UserAvailabilityOverride).where(UserAvailabilityOverride.user_id == user.id)
    
    if start_date:
        query = query.where(UserAvailabilityOverride.date >= start_date)
    if end_date:
        query = query.where(UserAvailabilityOverride.date <= end_date)
    
    query = query.order_by(UserAvailabilityOverride.date, UserAvailabilityOverride.start_time)
    result = await db.execute(query)
    return result.scalars().all()

@router.post("/me/availability/overrides", response_model=UserAvailabilityOverrideResponse)
async def create_availability_override(
    override: UserAvailabilityOverrideCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new availability override"""
    # Check for conflicts
    existing = await db.execute(
        select(UserAvailabilityOverride)
        .where(
            UserAvailabilityOverride.user_id == user.id,
            UserAvailabilityOverride.date == override.date,
            UserAvailabilityOverride.start_time == override.start_time,
            UserAvailabilityOverride.end_time == override.end_time
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Override already exists for this date and time")
    
    new_override = UserAvailabilityOverride(
        user_id=user.id,
        date=override.date,
        start_time=override.start_time,
        end_time=override.end_time,
        reason=override.reason
    )
    db.add(new_override)
    await db.commit()
    await db.refresh(new_override)
    
    logger.info(f"Created availability override for user {user.id}")
    return new_override

# NEW: Batch endpoints for availability overrides
@router.post("/me/availability/overrides/batch", response_model=AvailabilityOverrideBatchResponse)
async def create_availability_override_batch(
    batch_data: AvailabilityOverrideBatchCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create multiple availability overrides at once (When2Meet style)"""
    created_overrides = []
    errors = []
    
    for override in batch_data.overrides:
        try:
            # Check for conflicts
            existing = await db.execute(
                select(UserAvailabilityOverride)
                .where(
                    UserAvailabilityOverride.user_id == user.id,
                    UserAvailabilityOverride.date == override.date,
                    UserAvailabilityOverride.start_time == override.start_time,
                    UserAvailabilityOverride.end_time == override.end_time
                )
            )
            if existing.scalars().first():
                errors.append(f"Override already exists: {override.date} {override.start_time}-{override.end_time}")
                continue
            
            new_override = UserAvailabilityOverride(
                user_id=user.id,
                date=override.date,
                start_time=override.start_time,
                end_time=override.end_time,
                reason=override.reason
            )
            db.add(new_override)
            created_overrides.append(new_override)
            
        except Exception as e:
            errors.append(f"Error creating override {override.date} {override.start_time}-{override.end_time}: {str(e)}")
    
    if created_overrides:
        await db.commit()
        for override in created_overrides:
            await db.refresh(override)
    
    logger.info(f"Created {len(created_overrides)} availability overrides for user {user.id}")
    return AvailabilityOverrideBatchResponse(
        created_overrides=created_overrides,
        errors=errors,
        total_created=len(created_overrides),
        total_errors=len(errors)
    )

@router.delete("/me/availability/overrides/batch")
async def delete_availability_override_batch(
    target_date: Optional[date] = Query(None, description="Delete all overrides for specific date"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete all availability overrides for a specific date (When2Meet style clear)"""
    query = select(UserAvailabilityOverride).where(UserAvailabilityOverride.user_id == user.id)
    
    if target_date is not None:
        query = query.where(UserAvailabilityOverride.date == target_date)
    
    result = await db.execute(query)
    overrides_to_delete = result.scalars().all()
    
    for override in overrides_to_delete:
        await db.delete(override)
    
    await db.commit()
    
    logger.info(f"Deleted {len(overrides_to_delete)} availability overrides for user {user.id}")
    return {"message": f"Deleted {len(overrides_to_delete)} availability overrides"}

@router.put("/me/availability/overrides/{override_id}", response_model=UserAvailabilityOverrideResponse)
async def update_availability_override(
    override_id: int,
    override: UserAvailabilityOverrideCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a availability override"""
    result = await db.execute(
        select(UserAvailabilityOverride)
        .where(
            UserAvailabilityOverride.id == override_id,
            UserAvailabilityOverride.user_id == user.id
        )
    )
    existing = result.scalars().first()
    
    if not existing:
        raise HTTPException(status_code=404, detail="Override not found")
    
    # Update fields
    existing.date = override.date
    existing.start_time = override.start_time
    existing.end_time = override.end_time
    existing.reason = override.reason
    
    await db.commit()
    await db.refresh(existing)
    
    logger.info(f"Updated availability override {override_id} for user {user.id}")
    return existing

@router.delete("/me/availability/overrides/{override_id}")
async def delete_availability_override(
    override_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a availability override"""
    result = await db.execute(
        select(UserAvailabilityOverride)
        .where(
            UserAvailabilityOverride.id == override_id,
            UserAvailabilityOverride.user_id == user.id
        )
    )
    existing = result.scalars().first()
    
    if not existing:
        raise HTTPException(status_code=404, detail="Override not found")
    
    await db.delete(existing)
    await db.commit()
    
    logger.info(f"Deleted availability override {override_id} for user {user.id}")
    return {"message": "Override deleted successfully"}

# ============================================================================
# CALL PREFERENCES ENDPOINTS
# ============================================================================

@router.put("/me/call-preferences/{matched_user_id}", response_model=CallPreferenceResponse)
async def update_call_preference(
    matched_user_id: int,
    preference: CallPreferenceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update call preference for a specific match"""
    # Verify the match exists
    match_result = await db.execute(
        select(Match).where(
            ((Match.user_id == user.id) & (Match.matched_user_id == matched_user_id)) |
            ((Match.user_id == matched_user_id) & (Match.matched_user_id == user.id))
        )
    )
    match = match_result.scalar_one_or_none()
    
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    # Get or create call preference
    preference_result = await db.execute(
        select(UserMatchCallPreferences).where(
            UserMatchCallPreferences.user_id == user.id,
            UserMatchCallPreferences.matched_user_id == matched_user_id
        )
    )
    call_preference = preference_result.scalar_one_or_none()
    
    if not call_preference:
        call_preference = UserMatchCallPreferences(
            user_id=user.id,
            matched_user_id=matched_user_id,
            status=preference.status
        )
        db.add(call_preference)
    else:
        call_preference.status = preference.status
        call_preference.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(call_preference)
    
    logger.info(f"Updated call preference for user {user.id} with {matched_user_id}: {preference.status}")
    return call_preference

@router.get("/me/call-preferences", response_model=List[CallPreferenceResponse])
async def get_call_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None, description="Filter by status")
):
    """Get user's call preferences for all matches"""
    query = select(UserMatchCallPreferences).where(UserMatchCallPreferences.user_id == user.id)
    
    if status:
        query = query.where(UserMatchCallPreferences.status == status)
    
    result = await db.execute(query)
    return result.scalars().all()

# ============================================================================
# TIMEZONE ENDPOINTS
# ============================================================================

@router.get("/me/timezone", response_model=UserTimezoneResponse)
async def get_timezone(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's timezone information"""
    result = await db.execute(
        select(UserTimezone).where(UserTimezone.user_id == user.id)
    )
    timezone_info = result.scalar_one_or_none()
    
    if not timezone_info:
        # Return default timezone
        return UserTimezoneResponse(
            user_id=user.id,
            timezone="UTC",
            timezone_offset=0,
            dst_enabled=False
        )
    
    return timezone_info

@router.put("/me/timezone", response_model=UserTimezoneResponse)
async def update_timezone(
    timezone_data: UserTimezoneCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user's timezone information"""
    result = await db.execute(
        select(UserTimezone).where(UserTimezone.user_id == user.id)
    )
    timezone_info = result.scalar_one_or_none()
    
    if not timezone_info:
        # Create new timezone record
        timezone_info = UserTimezone(
            user_id=user.id,
            timezone=timezone_data.timezone,
            timezone_offset=timezone_data.timezone_offset,
            dst_enabled=timezone_data.dst_enabled
        )
        db.add(timezone_info)
    else:
        # Update existing record
        timezone_info.timezone = timezone_data.timezone
        timezone_info.timezone_offset = timezone_data.timezone_offset
        timezone_info.dst_enabled = timezone_data.dst_enabled
        timezone_info.last_updated = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(timezone_info)
    
    logger.info(f"Updated timezone for user {user.id}: {timezone_data.timezone}")
    return timezone_info

# ============================================================================
# SCHEDULING PREFERENCES ENDPOINTS
# ============================================================================

@router.get("/me/preferences", response_model=UserSchedulingPreferenceResponse)
async def get_scheduling_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's scheduling preferences"""
    result = await db.execute(
        select(UserSchedulingPreferences).where(UserSchedulingPreferences.user_id == user.id)
    )
    preferences = result.scalar_one_or_none()
    
    if not preferences:
        # Return default preferences
        return UserSchedulingPreferenceResponse(
            user_id=user.id,
            max_calls_per_week=5,
            min_notice_hours=2,
            max_advance_days=7,
            preferred_start_time=time(18, 0),
            preferred_end_time=time(22, 0),
            email_notifications=True,
            push_notifications=True,
            reminder_hours_before=1
        )
    
    return preferences

@router.put("/me/preferences", response_model=UserSchedulingPreferenceResponse)
async def update_scheduling_preferences(
    preferences_data: UserSchedulingPreferenceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user's scheduling preferences"""
    result = await db.execute(
        select(UserSchedulingPreferences).where(UserSchedulingPreferences.user_id == user.id)
    )
    preferences = result.scalar_one_or_none()
    
    if not preferences:
        # Create new preferences record
        preferences = UserSchedulingPreferences(
            user_id=user.id,
            max_calls_per_week=preferences_data.max_calls_per_week,
            min_notice_hours=preferences_data.min_notice_hours,
            max_advance_days=preferences_data.max_advance_days,
            preferred_start_time=preferences_data.preferred_start_time,
            preferred_end_time=preferences_data.preferred_end_time,
            email_notifications=preferences_data.email_notifications,
            push_notifications=preferences_data.push_notifications,
            reminder_hours_before=preferences_data.reminder_hours_before
        )
        db.add(preferences)
    else:
        # Update existing preferences
        preferences.max_calls_per_week = preferences_data.max_calls_per_week
        preferences.min_notice_hours = preferences_data.min_notice_hours
        preferences.max_advance_days = preferences_data.max_advance_days
        preferences.preferred_start_time = preferences_data.preferred_start_time
        preferences.preferred_end_time = preferences_data.preferred_end_time
        preferences.email_notifications = preferences_data.email_notifications
        preferences.push_notifications = preferences_data.push_notifications
        preferences.reminder_hours_before = preferences_data.reminder_hours_before
        preferences.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(preferences)
    
    logger.info(f"Updated scheduling preferences for user {user.id}")
    return preferences

# ============================================================================
# VIDEO CALL ENDPOINTS
# ============================================================================

@router.get("/me/calls", response_model=List[ScheduledCallResponse])
async def get_my_calls(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None, description="Filter by call status"),
    upcoming: bool = Query(True, description="Get upcoming calls (True) or past calls (False)")
):
    """Get user's scheduled calls with user names"""
    query = select(ScheduledCall).where(
        (ScheduledCall.user1_id == user.id) | (ScheduledCall.user2_id == user.id)
    )
    
    if status:
        query = query.where(ScheduledCall.status == status)
    
    if upcoming:
        # Show calls that haven't ended yet (covers both future and currently-active calls)
        query = query.where(ScheduledCall.scheduled_end_utc >= datetime.now(timezone.utc))
    else:
        query = query.where(ScheduledCall.scheduled_end_utc < datetime.now(timezone.utc))
    
    query = query.order_by(ScheduledCall.scheduled_start_utc)
    result = await db.execute(query)
    
    # Process results to populate user names and determine "other" user
    calls = []
    for row in result.all():
        call = row[0]  # ScheduledCall object
        
        # Get both user names
        user1_query = await db.execute(select(User).where(User.id == call.user1_id))
        user1 = user1_query.scalar_one_or_none()
        
        user2_query = await db.execute(select(User).where(User.id == call.user2_id))
        user2 = user2_query.scalar_one_or_none()
        
        # Determine which is the "other" user
        if call.user1_id == user.id:
            other_user_name = user2.name if user2 else "Unknown User"
            other_user_id = call.user2_id
        else:
            other_user_name = user1.name if user1 else "Unknown User"
            other_user_id = call.user1_id
        
        # Format datetime for iOS
        start_time_str = call.scheduled_start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_time_str = call.scheduled_end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        created_str = call.created_at.strftime('%Y-%m-%dT%H:%M:%SZ')
        updated_str = call.updated_at.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # Create response object with populated names
        call_response = ScheduledCallResponse(
            id=call.id,
            user_id=user.id,  # iOS compatibility
            match_id=call.match_id,
            user1_id=call.user1_id,
            user2_id=call.user2_id,
            user1_name=user1.name if user1 else None,
            user2_name=user2.name if user2 else None,
            other_user_name=other_user_name,
            other_user_id=other_user_id,
            start_time_utc=start_time_str,  # iOS expects string
            end_time_utc=end_time_str,      # iOS expects string
            scheduled_start_utc=call.scheduled_start_utc,
            scheduled_end_utc=call.scheduled_end_utc,
            duration_minutes=call.duration_minutes,
            status=call.status,
            user1_confirmed=call.user1_confirmed,
            user2_confirmed=call.user2_confirmed,
            user1_confirmed_at=call.user1_confirmed_at,
            user2_confirmed_at=call.user2_confirmed_at,
            call_room_id=call.call_room_id,
            call_started_at=call.call_started_at,
            call_ended_at=call.call_ended_at,
            actual_duration_minutes=call.actual_duration_minutes,
            original_call_id=call.original_call_id,
            reschedule_count=call.reschedule_count,
            user1_notified=call.user1_notified,
            user2_notified=call.user2_notified,
            reminder_sent=call.reminder_sent,
            created_at=call.created_at,
            updated_at=call.updated_at
        )
        calls.append(call_response)
    
    return calls

@router.get("/me/matches", response_model=List[dict])
async def get_my_matches_without_calls(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's unscheduled matches within the 48-hour scheduling window.

    Returns only matches where:
    - No scheduled call exists yet
    - No pending proposal exists yet (those appear in /proposals)
    - Match was created within the last 48 hours (Tier 2 window)

    Each result includes `initiator_id` (the user who swiped / User A).
    """
    from datetime import datetime, timezone, timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)

    # Matches within the 48h window, excluding expired/blocked
    matches_query = select(Match).where(
        ((Match.user_id == user.id) | (Match.matched_user_id == user.id))
        & (Match.created_at >= cutoff)
        & (~Match.status.in_(["expired", "blocked", "rejected"]))
    )
    matches_result = await db.execute(matches_query)
    matches = matches_result.scalars().all()

    # Match IDs that already have scheduled calls (any status)
    calls_query = select(ScheduledCall.match_id).where(
        (ScheduledCall.user1_id == user.id) | (ScheduledCall.user2_id == user.id)
    )
    calls_result = await db.execute(calls_query)
    scheduled_match_ids = {row[0] for row in calls_result.fetchall()}

    # Match IDs that already have a pending proposal
    from app.models import SchedulingProposal as ProposalModel
    proposals_query = select(ProposalModel.match_id).where(
        ((ProposalModel.proposer_id == user.id) | (ProposalModel.receiver_id == user.id))
        & (ProposalModel.status == "pending")
    )
    proposals_result = await db.execute(proposals_query)
    proposed_match_ids = {row[0] for row in proposals_result.fetchall()}

    exclude_ids = scheduled_match_ids | proposed_match_ids

    unscheduled_matches = []
    for match in matches:
        if match.id in exclude_ids:
            continue

        if match.user_id == user.id:
            other_user_id = match.matched_user_id
        else:
            other_user_id = match.user_id

        other_user_query = await db.execute(select(User).where(User.id == other_user_id))
        other_user = other_user_query.scalar_one_or_none()

        # Deadline for scheduling (48h from match creation)
        deadline = None
        if match.created_at:
            dt = match.created_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            deadline = (dt + timedelta(hours=48)).isoformat()

        unscheduled_matches.append({
            "id": match.id,
            "user1_id": match.user_id,           # initiator (swiped right)
            "user2_id": match.matched_user_id,   # recipient
            "initiator_id": match.user_id,        # explicit field: User A
            "other_user_id": other_user_id,
            "other_user_name": other_user.name if other_user else "Unknown User",
            "created_at": match.created_at.isoformat() if match.created_at else None,
            "scheduling_deadline": deadline,
        })

    return unscheduled_matches

@router.post("/calls", response_model=ScheduledCallResponse)
async def schedule_call(
    call_data: ScheduledCallCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    logger.info(f"[API] schedule_call called by user {user.id} (firebase_uid={user.firebase_uid}) with data: {call_data}")
    try:
        # Verify user is a participant
        if user.id not in [call_data.user1_id, call_data.user2_id]:
            logger.warning(f"User {user.id} not a participant in call: {call_data.user1_id}, {call_data.user2_id}")
            raise HTTPException(status_code=403, detail="You can only schedule calls you're participating in")
        # Calculate end time from start time and duration
        scheduled_end_utc = call_data.scheduled_start_utc + timedelta(minutes=call_data.duration_minutes)
        logger.info(f"Checking conflicts for user1_id={call_data.user1_id}, user2_id={call_data.user2_id}, start={call_data.scheduled_start_utc}, end={scheduled_end_utc}")
        # For immediate calls (start time within 2 minutes of now), skip availability check —
        # the user is signaling "I'm available right now". Only block if there's an active call overlap.
        now_utc = datetime.now(timezone.utc)
        is_immediate = abs((call_data.scheduled_start_utc - now_utc).total_seconds()) <= 120
        if is_immediate:
            logger.info("Immediate call detected — skipping availability check, checking active call conflicts only")
            conflict_check = await db.execute(
                text("""SELECT EXISTS(
                    SELECT 1 FROM scheduled_calls
                    WHERE (user1_id = :user_id OR user2_id = :user_id)
                      AND status IN ('scheduled', 'in_progress')
                      AND (scheduled_start_utc < :end_time AND scheduled_end_utc > :start_time)
                )"""),
                {"user_id": call_data.user1_id, "start_time": call_data.scheduled_start_utc, "end_time": scheduled_end_utc}
            )
            user1_conflict = conflict_check.scalar()
            conflict_check = await db.execute(
                text("""SELECT EXISTS(
                    SELECT 1 FROM scheduled_calls
                    WHERE (user1_id = :user_id OR user2_id = :user_id)
                      AND status IN ('scheduled', 'in_progress')
                      AND (scheduled_start_utc < :end_time AND scheduled_end_utc > :start_time)
                )"""),
                {"user_id": call_data.user2_id, "start_time": call_data.scheduled_start_utc, "end_time": scheduled_end_utc}
            )
            user2_conflict = conflict_check.scalar()
        else:
            # Check for scheduling conflicts using database function
            conflict_check = await db.execute(
                text("SELECT check_scheduling_conflict(:user_id, :start_time, :end_time)"),
                {"user_id": call_data.user1_id, "start_time": call_data.scheduled_start_utc, "end_time": scheduled_end_utc}
            )
            user1_conflict = conflict_check.scalar()
            conflict_check = await db.execute(
                text("SELECT check_scheduling_conflict(:user_id, :start_time, :end_time)"),
                {"user_id": call_data.user2_id, "start_time": call_data.scheduled_start_utc, "end_time": scheduled_end_utc}
            )
            user2_conflict = conflict_check.scalar()
        logger.info(f"user1_conflict={user1_conflict}, user2_conflict={user2_conflict}")
        if user1_conflict or user2_conflict:
            logger.warning(f"Scheduling conflict detected for call: {call_data}")
            raise HTTPException(status_code=409, detail="Scheduling conflict detected - one or both users are not available at this time")
        # Create the scheduled call
        new_call = ScheduledCall(
            match_id=call_data.match_id,
            user1_id=call_data.user1_id,
            user2_id=call_data.user2_id,
            scheduled_start_utc=call_data.scheduled_start_utc,
            scheduled_end_utc=scheduled_end_utc,
            duration_minutes=call_data.duration_minutes
        )
        db.add(new_call)
        await db.commit()
        await db.refresh(new_call)
        logger.info(f"Scheduled call {new_call.id} for users {call_data.user1_id} and {call_data.user2_id}")

        # Update match_outcomes funnel: stamp call_scheduled_at (best-effort)
        try:
            outcome_q = await db.execute(
                select(MatchOutcome).where(MatchOutcome.match_id == new_call.match_id)
            )
            outcome = outcome_q.scalar_one_or_none()
            if outcome and outcome.call_scheduled_at is None:
                outcome.call_scheduled_at = datetime.now(timezone.utc)
                await db.commit()
        except Exception as exc:
            logger.warning(f"Failed to update match_outcomes.call_scheduled_at: {exc}")

        # Fetch user names for response
        user1_query = await db.execute(select(User).where(User.id == new_call.user1_id))
        user1 = user1_query.scalar_one_or_none()

        user2_query = await db.execute(select(User).where(User.id == new_call.user2_id))
        user2 = user2_query.scalar_one_or_none()

        # Determine which is the "other" user
        if new_call.user1_id == user.id:
            other_user_name = user2.name if user2 else "Unknown User"
            other_user_id = new_call.user2_id
            other_user = user2
        else:
            other_user_name = user1.name if user1 else "Unknown User"
            other_user_id = new_call.user1_id
            other_user = user1

        # S1 — notify the other participant that a call was just scheduled
        try:
            await push.notify_immediate_call_request(
                recipient=other_user, caller=user, call_id=new_call.id
            )
        except Exception as exc:
            logger.warning(f"[PUSH] S1 notification failed: {exc}")

        # Format datetime for iOS
        start_time_str = new_call.scheduled_start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_time_str = new_call.scheduled_end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

        # Return ScheduledCallResponse with all required fields
        return ScheduledCallResponse(
            id=new_call.id,
            user_id=user.id,
            match_id=new_call.match_id,
            user1_id=new_call.user1_id,
            user2_id=new_call.user2_id,
            user1_name=user1.name if user1 else None,
            user2_name=user2.name if user2 else None,
            other_user_name=other_user_name,
            other_user_id=other_user_id,
            start_time_utc=start_time_str,
            end_time_utc=end_time_str,
            scheduled_start_utc=new_call.scheduled_start_utc,
            scheduled_end_utc=new_call.scheduled_end_utc,
            duration_minutes=new_call.duration_minutes,
            status=new_call.status,
            user1_confirmed=new_call.user1_confirmed,
            user2_confirmed=new_call.user2_confirmed,
            user1_confirmed_at=new_call.user1_confirmed_at,
            user2_confirmed_at=new_call.user2_confirmed_at,
            call_room_id=new_call.call_room_id,
            call_started_at=new_call.call_started_at,
            call_ended_at=new_call.call_ended_at,
            actual_duration_minutes=new_call.actual_duration_minutes,
            original_call_id=new_call.original_call_id,
            reschedule_count=new_call.reschedule_count,
            user1_notified=new_call.user1_notified,
            user2_notified=new_call.user2_notified,
            reminder_sent=new_call.reminder_sent,
            created_at=new_call.created_at,
            updated_at=new_call.updated_at
        )
    except Exception as e:
        logger.error(f"Exception in schedule_call: {e}", exc_info=True)
        raise

@router.put("/calls/{call_id}/extend", response_model=ScheduledCallResponse)
async def extend_call(
    call_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Extend a call by 5 minutes (up to 30 minutes total)"""
    result = await db.execute(
        select(ScheduledCall).where(ScheduledCall.id == call_id)
    )
    call = result.scalars().first()
    
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    
    # Verify user is a participant
    if user.id not in [call.user1_id, call.user2_id]:
        raise HTTPException(status_code=403, detail="You can only extend calls you're participating in")
    
    # Check if call is in progress
    if call.status != "in_progress":
        raise HTTPException(status_code=400, detail="Can only extend calls that are in progress")
    
    # Check if we can extend (max 30 minutes total)
    current_duration = call.actual_duration_minutes or 15
    if current_duration >= 30:
        raise HTTPException(status_code=400, detail="Call cannot be extended beyond 30 minutes")
    
    # Extend by 5 minutes
    call.actual_duration_minutes = min(current_duration + 5, 30)
    
    await db.commit()
    await db.refresh(call)
    
    logger.info(f"Extended call {call_id} to {call.actual_duration_minutes} minutes")
    return call

@router.put("/calls/{call_id}/confirm", response_model=ScheduledCallResponse)
async def confirm_call(
    call_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Confirm a scheduled call (mark as confirmed by user)"""
    result = await db.execute(
        select(ScheduledCall)
        .where(ScheduledCall.id == call_id)
        .options(selectinload(ScheduledCall.user1), selectinload(ScheduledCall.user2))
    )
    call = result.scalars().first()
    
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    
    # Check if user is part of this call
    if call.user1_id != user.id and call.user2_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to confirm this call")
    
    # Update confirmation status
    if call.user1_id == user.id:
        call.user1_confirmed = True
        call.user1_confirmed_at = datetime.now(timezone.utc)
    else:
        call.user2_confirmed = True
        call.user2_confirmed_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(call)
    
    logger.info(f"Call {call_id} confirmed by user {user.id}")
    return call

@router.post("/calls/{call_id}/cancel", response_model=ScheduledCallResponse)
async def cancel_call(
    call_id: int,
    reason: str = "User cancelled",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel a scheduled call (can be used for rejections)"""
    result = await db.execute(
        select(ScheduledCall)
        .where(ScheduledCall.id == call_id)
        .options(selectinload(ScheduledCall.user1), selectinload(ScheduledCall.user2))
    )
    call = result.scalars().first()
    
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    
    # Check if user is part of this call
    if call.user1_id != user.id and call.user2_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to cancel this call")
    
    # Check if call can be cancelled
    if call.status not in ['scheduled', 'in_progress']:
        raise HTTPException(status_code=400, detail="Call cannot be cancelled in its current status")
    
    # Update call status
    call.status = 'cancelled'
    call.call_ended_at = datetime.now(timezone.utc)
    
    # Update UserMatchCallPreferences status based on who cancelled
    if call.user1_id == user.id:
        # User1 cancelled - update their preference to 'doesnt_want_to_call'
        preference_result = await db.execute(
            select(UserMatchCallPreferences)
            .where(
                UserMatchCallPreferences.user_id == call.user1_id,
                UserMatchCallPreferences.matched_user_id == call.user2_id
            )
        )
        preference = preference_result.scalars().first()
        if preference:
            preference.status = 'doesnt_want_to_call'
    else:
        # User2 cancelled - update their preference to 'doesnt_want_to_call'
        preference_result = await db.execute(
            select(UserMatchCallPreferences)
            .where(
                UserMatchCallPreferences.user_id == call.user2_id,
                UserMatchCallPreferences.matched_user_id == call.user1_id
            )
        )
        preference = preference_result.scalars().first()
        if preference:
            preference.status = 'doesnt_want_to_call'
    
    await db.commit()
    await db.refresh(call)
    
    logger.info(f"Call {call_id} cancelled by user {user.id} with reason: {reason}")
    return call

# ============================================================================
# AVAILABILITY CHECKING ENDPOINTS
# ============================================================================

@router.post("/availability/check", response_model=AvailabilityCheckResponse)
async def check_availability(
    request: AvailabilityCheckRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Check if a user is available during a specific time period"""
    # Use database function to check for conflicts
    conflict_check = await db.execute(
        text("SELECT check_scheduling_conflict(:user_id, :start_time, :end_time)"),
        {"user_id": request.user_id, "start_time": request.start_time_utc, "end_time": request.end_time_utc}
    )
    has_conflict = conflict_check.scalar()
    
    return AvailabilityCheckResponse(
        user_id=request.user_id,
        is_available=not has_conflict,
        conflicts=[] if not has_conflict else [{"reason": "Scheduling conflict detected"}]
    )

@router.post("/availability/common", response_model=FindCommonAvailabilityResponse)
async def find_common_availability(
    request: FindCommonAvailabilityRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Find common availability between two users using database function"""
    # Use the UTC-aware database function to find common availability
    result = await db.execute(
        text("SELECT * FROM find_common_availability_utc(:user1_id, :user2_id, :start_date, :end_date)"),
        {"user1_id": request.user1_id, "user2_id": request.user2_id, "start_date": request.start_date, "end_date": request.end_date}
    )
    common_slots = result.fetchall()

    # Convert to response format - slots are already in UTC from SQL function
    available_slots = []
    for slot in common_slots:
        # SQL function returns TIMESTAMP WITH TIME ZONE, ensure it's timezone-aware
        start_utc = slot.start_time_utc
        end_utc = slot.end_time_utc

        # Make timezone-aware if not already
        if start_utc.tzinfo is None:
            start_utc = start_utc.replace(tzinfo=timezone.utc)
        if end_utc.tzinfo is None:
            end_utc = end_utc.replace(tzinfo=timezone.utc)

        available_slots.append({
            "start_time_utc": start_utc,
            "end_time_utc": end_utc,
            "user1_local_time": f"{slot.slot_date} {start_utc.strftime('%H:%M')}",
            "user2_local_time": f"{slot.slot_date} {start_utc.strftime('%H:%M')}"
        })

    # Sort by start time and take earliest results
    available_slots.sort(key=lambda x: x["start_time_utc"])
    available_slots = available_slots[:10]

    return FindCommonAvailabilityResponse(
        available_slots=available_slots,
        total_slots_checked=len(common_slots)
    )

@router.post("/availability/immediate", response_model=FindCommonAvailabilityResponse)
async def find_immediate_common_availability(
    request: dict,  # Expecting {"user1_id": int, "user2_id": int}
    db: AsyncSession = Depends(get_db)
):
    """Find immediate common availability between two matched users for video calls (next 7 days, max 3 slots)"""
    import logging
    logger = logging.getLogger(__name__)

    try:
        user1_id = request.get("user1_id")
        user2_id = request.get("user2_id")

        if not user1_id or not user2_id:
            raise HTTPException(status_code=400, detail="user1_id and user2_id are required")

        logger.info(f"[availability/immediate] Looking up availability for users {user1_id} and {user2_id}")

        # Verify users exist and are matched
        from app.models import Match
        match_result = await db.execute(
            select(Match).where(
                ((Match.user_id == user1_id) & (Match.matched_user_id == user2_id)) |
                ((Match.user_id == user2_id) & (Match.matched_user_id == user1_id))
            )
        )
        match = match_result.scalars().first()
        if not match:
            raise HTTPException(status_code=403, detail="Users are not matched")

        logger.info(f"[availability/immediate] Match found, querying SQL function...")

        # Use the UTC-aware database function to find immediate common availability (next 7 days, max 3 slots)
        result = await db.execute(
            text("SELECT * FROM find_immediate_common_availability_utc(:user1_id, :user2_id)"),
            {"user1_id": user1_id, "user2_id": user2_id}
        )
        common_slots = result.fetchall()

        logger.info(f"[availability/immediate] Found {len(common_slots)} common slots")

        # Convert to response format - slots are already in UTC from SQL function
        available_slots = []
        for slot in common_slots:
            # SQL function returns TIMESTAMP WITH TIME ZONE, ensure it's timezone-aware
            start_utc = slot.start_time_utc
            end_utc = slot.end_time_utc

            # Make timezone-aware if not already
            if start_utc.tzinfo is None:
                start_utc = start_utc.replace(tzinfo=timezone.utc)
            if end_utc.tzinfo is None:
                end_utc = end_utc.replace(tzinfo=timezone.utc)

            available_slots.append({
                "start_time_utc": start_utc,
                "end_time_utc": end_utc,
                "user1_local_time": f"{slot.slot_date} {start_utc.strftime('%H:%M')}",
                "user2_local_time": f"{slot.slot_date} {start_utc.strftime('%H:%M')}"
            })

        return FindCommonAvailabilityResponse(
            available_slots=available_slots,
            total_slots_checked=len(common_slots)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[availability/immediate] Error: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {type(e).__name__}: {str(e)}")

# ============================================================================
# DEFAULT AVAILABILITY ENDPOINTS (iOS App Compatibility)
# ============================================================================

@router.get("/availability/default")
async def get_default_availability(
    user_id: int = Query(..., description="User ID"),
    db: AsyncSession = Depends(get_db)
):
    """Get user's default availability schedule (iOS app compatibility)"""
    try:
        # Check if user exists
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Query actual default availability from database
        from app.models import UserDefaultAvailability
        availability_result = await db.execute(
            select(UserDefaultAvailability)
            .where(UserDefaultAvailability.user_id == user_id)
            .order_by(UserDefaultAvailability.day_of_week, UserDefaultAvailability.hour, UserDefaultAvailability.minute)
        )
        availability_slots = availability_result.scalars().all()
        
        # Convert to time slots format expected by iOS app
        time_slots = []
        for slot in availability_slots:
            if slot.is_available:
                time_slots.append({
                    "id": slot.id,
                    "day_of_week": slot.day_of_week,
                    "hour": slot.hour,
                    "minute": slot.minute,
                    "is_available": slot.is_available,
                    "is_override": False  # Default availability slots are not overrides
                })
        
        logger.info(f"Retrieved {len(time_slots)} default availability slots for user {user_id}")
        
        return {
            "user_id": user_id,
            "time_slots": time_slots
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting default availability for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/availability/default")
async def update_default_availability(
    request: dict,
    db: AsyncSession = Depends(get_db)
):
    """Update user's default availability schedule (iOS app compatibility)
    
    When default schedule is updated, it COMPLETELY REPLACES the override schedule
    with the new default pattern, aligned to current week starting from today.
    """
    try:
        user_id = request.get("user_id")
        time_slots = request.get("time_slots", [])
        
        # Check if user exists
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Clear existing default availability for this user
        from app.models import UserDefaultAvailability, UserOverrideAvailability
        from sqlalchemy import delete
        await db.execute(delete(UserDefaultAvailability).where(UserDefaultAvailability.user_id == user_id))
        
        # Deduplicate time slots to prevent constraint violations
        # iOS app sometimes sends duplicate slots (existing + newly selected)
        unique_slots = {}
        for slot in time_slots:
            key = (slot.get("day_of_week"), slot.get("hour"), slot.get("minute"))
            if key not in unique_slots:
                unique_slots[key] = slot
        
        # Insert deduplicated availability slots with validation
        for slot in unique_slots.values():
            # Validate day_of_week is in correct range (0-6, Sunday=0)
            day_of_week = slot.get("day_of_week")
            if day_of_week is None or day_of_week < 0 or day_of_week > 6:
                logger.warning(f"Invalid day_of_week: {day_of_week}, skipping slot")
                continue
                
            # Validate hour and minute
            hour = slot.get("hour")
            minute = slot.get("minute")
            if hour is None or hour < 0 or hour > 23:
                logger.warning(f"Invalid hour: {hour}, skipping slot")
                continue
            if minute is None or minute not in [0, 30]:
                logger.warning(f"Invalid minute: {minute}, skipping slot")
                continue
                
            availability_slot = UserDefaultAvailability(
                user_id=user_id,
                day_of_week=day_of_week,
                hour=hour,
                minute=minute,
                is_available=slot.get("is_available", True)  # <-- FIXED: use frontend value!
            )
            db.add(availability_slot)
        
        # ✅ DEFAULT→OVERRIDE FIX: COMPLETELY REPLACE override schedule with new default pattern
        # aligned to current week starting from today
        logger.info(f"DEFAULT→OVERRIDE FIX: Replacing override schedule with new default pattern for user {user_id}")
        
        # 1. Clear ALL existing override availability for this user
        # Use the CORRECT model that the GET endpoint actually reads from
        from app.models import UserAvailabilityOverride
        await db.execute(delete(UserAvailabilityOverride).where(UserAvailabilityOverride.user_id == user_id))
        logger.info(f"DEFAULT→OVERRIDE FIX: Cleared all existing UserAvailabilityOverride for user {user_id}")
        
        # 2. Populate override schedule with new default pattern, aligned to current week
        from datetime import date, timedelta, time
        today = date.today()
        current_weekday = today.weekday()  # Monday=0, Sunday=6
        current_day_of_week = (current_weekday + 1) % 7  # Convert to Sunday=0 format
        
        logger.info(f"DEFAULT→OVERRIDE FIX: Today is {today}, weekday={current_weekday}, day_of_week={current_day_of_week}")
        
        # Create override slots for the next 7 days starting from today
        override_slots_created = 0
        for day_offset in range(7):  # 7 days starting from today
            target_date = today + timedelta(days=day_offset)
            target_weekday = target_date.weekday()  # Monday=0, Sunday=6  
            target_day_of_week = (target_weekday + 1) % 7  # Convert to Sunday=0 format
            
            logger.info(f"DEFAULT→OVERRIDE FIX: Day {day_offset}: {target_date} (weekday={target_weekday}, day_of_week={target_day_of_week})")
            
            # Find all default availability slots for this day of week
            for slot in unique_slots.values():
                if slot.get("day_of_week") == target_day_of_week and slot.get("is_available", False):
                    hour = slot.get("hour")
                    minute = slot.get("minute")
                    
                    if hour is not None and minute is not None:
                        # Create start and end times (30-minute slots)
                        start_time = time(hour, minute, 0)
                        
                        # Calculate end time (30 minutes later)
                        if minute == 0:
                            end_time = time(hour, 30, 0)
                        elif minute == 30:
                            if hour == 23:
                                end_time = time(23, 59, 0)  # 23:30 -> 23:59
                            else:
                                end_time = time(hour + 1, 0, 0)
                        else:
                            continue  # Skip invalid minute values
                        
                        # ✅ FIX: Use UserAvailabilityOverride (date-based) not UserOverrideAvailability  
                        override_slot = UserAvailabilityOverride(
                            user_id=user_id,
                            date=target_date,  # Use actual date for each day
                            start_time=start_time,
                            end_time=end_time
                        )
                        db.add(override_slot)
                        override_slots_created += 1
                        
                        logger.info(f"DEFAULT→OVERRIDE FIX: Created slot: {target_date} {start_time}-{end_time} (from default day_of_week={target_day_of_week})")
        
        logger.info(f"DEFAULT→OVERRIDE FIX: Created {override_slots_created} override slots aligned to current week")
        
        await db.commit()
        logger.info(f"Updated default availability for user {user_id} with {len(unique_slots)} unique time slots (from {len(time_slots)} total)")
        logger.info(f"SCHEDULE FIX: Successfully replaced override schedule with {override_slots_created} slots aligned to today ({today})")
        
        return {
            "user_id": user_id,
            "time_slots": list(unique_slots.values()),
            "override_slots_created": override_slots_created,
            "aligned_to_date": today.isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating default availability for user {user_id}: {str(e)}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/availability/override")
async def get_override_availability(
    user_id: int = Query(..., description="User ID"),
    week_start_date: str = Query(None, description="Week start date (YYYY-MM-DD)"),
    start_date: str = Query(None, description="Rolling start date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db)
):
    """Get user's override availability for a specific week (iOS app compatibility)"""
    try:
        # Check if user exists
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Determine the date range to query
        from datetime import datetime
        if start_date:
            # Rolling 7 days starting from the provided start_date
            query_start = datetime.strptime(start_date, "%Y-%m-%d").date()
            logger.info(f"Using rolling start_date: {start_date} (rolling 7 days)")
        elif week_start_date:
            # Traditional week start (backward compatibility)
            query_start = datetime.strptime(week_start_date, "%Y-%m-%d").date()
            logger.info(f"Using week_start_date: {week_start_date}")
        else:
            raise HTTPException(status_code=400, detail="Either week_start_date or start_date parameter is required")
        
        query_end = query_start + timedelta(days=7)
        
        # Query actual override availability from database
        from app.models import UserAvailabilityOverride
        override_result = await db.execute(
            select(UserAvailabilityOverride)
            .where(
                UserAvailabilityOverride.user_id == user_id,
                UserAvailabilityOverride.date >= query_start,
                UserAvailabilityOverride.date < query_end
            )
            .order_by(UserAvailabilityOverride.date, UserAvailabilityOverride.start_time)
        )
        override_slots = override_result.scalars().all()
        
        # ✅ PERSISTENCE FIX: Only return actual saved slots, not all possible slots
        # Convert override slots to When2Meet-style time slots format expected by iOS app
        time_slots = []
        
        logger.info(f"🔧 [PERSISTENCE_FIX] Converting {len(override_slots)} actual override slots to iOS format")
        
        for slot in override_slots:
            # Convert date to day_of_week relative to query_start
            days_from_start = (slot.date - query_start).days
            if 0 <= days_from_start < 7:  # Only include slots within our 7-day range
                current_date = slot.date
                python_weekday = current_date.weekday()  # Monday=0, Sunday=6
                day_of_week = (python_weekday + 1) % 7  # Convert to Sunday=0
                
                # Extract hour and minute from start_time
                hour = slot.start_time.hour
                minute = slot.start_time.minute
                
                # Generate slot ID (consistent with iOS app expectations)
                slot_id = days_from_start * 10000 + hour * 100 + minute
                
                # Calculate end time
                if minute == 0:
                    end_time = f"{hour:02d}:30"
                elif minute == 30:
                    if hour == 23:
                        end_time = "23:59"
                    else:
                        end_time = f"{hour+1:02d}:00"
                else:
                    end_time = f"{hour:02d}:{minute+30:02d}"
                
                time_slots.append({
                    "id": slot_id,
                    "date": current_date.isoformat(),
                    "start_time": f"{hour:02d}:{minute:02d}",
                    "end_time": end_time,
                    "day_of_week": day_of_week,
                    "hour": hour,
                    "minute": minute,
                    "is_available": True,  # Only available slots are saved, so all returned slots are available
                    "is_override": True
                })
                
                logger.info(f"🔧 [PERSISTENCE_FIX] Converted slot: {current_date} {hour:02d}:{minute:02d} (day_of_week={day_of_week})")
        
        logger.info(f"🔧 [PERSISTENCE_FIX] Successfully converted {len(time_slots)} available slots (instead of generating 336 mostly-false slots)")
        
        # Use the appropriate date parameter for response
        response_date = start_date if start_date else week_start_date
        logger.info(f"Retrieved {len(override_slots)} actual override slots, generated {len(time_slots)} total slots for user {user_id}, date range: {response_date}")
        
        return {
            "user_id": user_id,
            "week_start_date": response_date,
            "time_slots": time_slots
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting override availability for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/availability/override")
async def update_override_availability(
    request: dict,
    db: AsyncSession = Depends(get_db)
):
    """Update user's override availability for a specific week (iOS app compatibility)"""
    try:
        user_id = request.get("user_id")
        week_start_date = request.get("week_start_date")
        start_date = request.get("start_date")  # Support rolling start date
        time_slots = request.get("time_slots", [])
        
        # Check if user exists
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Determine the date range to use
        from datetime import datetime
        if start_date:
            # Rolling 7 days starting from the provided start_date
            query_start = datetime.strptime(start_date, "%Y-%m-%d").date()
            logger.info(f"Saving override with rolling start_date: {start_date}")
        elif week_start_date:
            # Traditional week start (backward compatibility)
            query_start = datetime.strptime(week_start_date, "%Y-%m-%d").date()
            logger.info(f"Saving override with week_start_date: {week_start_date}")
        else:
            raise HTTPException(status_code=400, detail="Either week_start_date or start_date parameter is required")
        
        # Clear existing override availability for this user and date range
        from app.models import UserAvailabilityOverride
        from sqlalchemy import delete
        query_end = query_start + timedelta(days=7)
        await db.execute(
            delete(UserAvailabilityOverride).where(
                UserAvailabilityOverride.user_id == user_id,
                UserAvailabilityOverride.date >= query_start,
                UserAvailabilityOverride.date < query_end
            )
        )
        
        # Handle When2Meet-style time slots (day_of_week, hour, minute format)
        # Convert to date-based format for storage
        override_slots = []
        available_slot_count = 0
        for slot in time_slots:
            if slot.get("is_available", False):  # Only save available slots
                available_slot_count += 1
                day_of_week = slot.get("day_of_week")
                hour = slot.get("hour")
                minute = slot.get("minute")
                
                if day_of_week is not None and hour is not None and minute is not None:
                    # Validate hour and minute ranges
                    if not (0 <= hour <= 23):
                        logger.warning(f"Invalid hour {hour} for slot {slot}, skipping")
                        continue
                    if minute not in [0, 30]:
                        logger.warning(f"Invalid minute {minute} for slot {slot}, skipping")
                        continue
                    
                    # For rolling dates, calculate the actual date based on day offset
                    # day_of_week in this context is relative to the query_start date
                    if start_date:
                        # For rolling dates, use direct day mapping from the 7-day period
                        # Find the day offset that matches the day_of_week
                        for day_offset in range(7):
                            check_date = query_start + timedelta(days=day_offset)
                            check_weekday = (check_date.weekday() + 1) % 7  # Convert to Sunday=0
                            if check_weekday == day_of_week:
                                slot_date = check_date
                                break
                        else:
                            logger.warning(f"Could not map day_of_week {day_of_week} for rolling date, skipping")
                            continue
                    else:
                        # Traditional week calculation
                        days_to_add = (day_of_week - query_start.weekday()) % 7
                        slot_date = query_start + timedelta(days=days_to_add)
                    
                    # Create start and end times (30-minute slots)
                    start_time = time(hour, minute, 0)
                    
                    # Calculate end time (30 minutes later)
                    if minute == 0:
                        end_time = time(hour, 30, 0)
                    elif minute == 30:
                        if hour == 23:
                            # 23:30 -> 00:00 (next day, but we'll handle this as 23:59 for now)
                            end_time = time(23, 59, 0)
                        else:
                            end_time = time(hour + 1, 0, 0)
                    else:
                        logger.warning(f"Invalid minute {minute} for slot {slot}, skipping")
                        continue
                    
                    override_slot = UserAvailabilityOverride(
                        user_id=user_id,
                        date=slot_date,
                        start_time=start_time,
                        end_time=end_time
                    )
                    override_slots.append(override_slot)
        
        # Add all override slots to database
        for slot in override_slots:
            db.add(slot)
        
        await db.commit()
        
        # Use the appropriate date parameter for response
        response_date = start_date if start_date else week_start_date
        logger.info(f"Updated override availability for user {user_id} for date {response_date} with {len(override_slots)} time slots (from {available_slot_count} available slots)")
        
        return {
            "user_id": user_id,
            "week_start_date": response_date,
            "time_slots": time_slots  # Return the original When2Meet format
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating override availability for user {user_id}: {str(e)}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/availability/weekly")
async def get_weekly_availability_ios(
    user_id: int = Query(..., description="User ID"),
    week_start_date: str = Query(..., description="Week start date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db)
):
    """Get user's effective availability for a specific week (iOS app compatibility)"""
    try:
        # Check if user exists
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # For now, return empty weekly availability
        # In a real implementation, you would combine default + override availability
        empty_time_slots = []
        
        return {
            "user_id": user_id,
            "week_start_date": week_start_date,
            "time_slots": empty_time_slots
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting weekly availability for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# COMPREHENSIVE SCHEDULE ENDPOINTS
# ============================================================================

@router.get("/me/schedule", response_model=UserScheduleResponse)
async def get_complete_schedule(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's complete schedule including availability, overrides, preferences, and calls"""
    # Load user with all relationships
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.weekly_availability),
            selectinload(User.availability_overrides),
            selectinload(User.timezone_info),
            selectinload(User.scheduling_preferences)
        )
        .where(User.id == user.id)
    )
    user_with_relations = result.scalars().first()
    
    # Get upcoming and past calls
    upcoming_calls_result = await db.execute(
        select(ScheduledCall)
        .where(
            (ScheduledCall.user1_id == user.id) | (ScheduledCall.user2_id == user.id),
            ScheduledCall.scheduled_start_utc >= datetime.now(timezone.utc)
        )
        .order_by(ScheduledCall.scheduled_start_utc)
    )
    upcoming_calls = upcoming_calls_result.scalars().all()

    past_calls_result = await db.execute(
        select(ScheduledCall)
        .where(
            (ScheduledCall.user1_id == user.id) | (ScheduledCall.user2_id == user.id),
            ScheduledCall.scheduled_start_utc < datetime.now(timezone.utc)
        )
        .order_by(ScheduledCall.scheduled_start_utc.desc())
        .limit(10)  # Limit to last 10 calls
    )
    past_calls = past_calls_result.scalars().all()
    
    # Check for upcoming overrides (next 7 days)
    upcoming_overrides_result = await db.execute(
        select(UserAvailabilityOverride)
        .where(
            UserAvailabilityOverride.user_id == user.id,
            UserAvailabilityOverride.date >= date.today(),
            UserAvailabilityOverride.date <= date.today() + timedelta(days=7)
        )
    )
    upcoming_overrides = upcoming_overrides_result.scalars().all()
    
    return UserScheduleResponse(
        user_id=user.id,
        weekly_availability=user_with_relations.weekly_availability,
        overrides=user_with_relations.availability_overrides,
        has_upcoming_overrides=len(upcoming_overrides) > 0,
        timezone=user_with_relations.timezone_info,
        preferences=user_with_relations.scheduling_preferences,
        upcoming_calls=upcoming_calls,
        past_calls=past_calls
    )

@router.post("/debug/test-insert")
async def debug_test_insert(db: AsyncSession = Depends(get_db)):
    """Minimal test: Insert a record for user 75 and return count after insert."""
    from app.models import UserDefaultAvailability
    from sqlalchemy import select, delete
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("🔍 [DEBUG] Starting debug test insert for user 75")
        
        # Delete existing
        delete_result = await db.execute(delete(UserDefaultAvailability).where(UserDefaultAvailability.user_id == 75))
        logger.info(f"🔍 [DEBUG] Deleted {delete_result.rowcount} existing records for user 75")
        
        # Insert test
        test_slot = UserDefaultAvailability(
            user_id=75,
            day_of_week=2,
            hour=12,
            minute=0,
            is_available=True
        )
        db.add(test_slot)
        logger.info("🔍 [DEBUG] Added test slot to session")
        
        logger.info("🔍 [DEBUG] About to commit test insert")
        await db.commit()
        logger.info("🔍 [DEBUG] Successfully committed test insert")
        
        # Query count
        result = await db.execute(select(UserDefaultAvailability).where(UserDefaultAvailability.user_id == 75))
        records = result.scalars().all()
        logger.info(f"🔍 [DEBUG] Found {len(records)} records after insert")
        
        return {"count": len(records), "records": [dict(day=s.day_of_week, hour=s.hour, minute=s.minute, avail=s.is_available) for s in records]}
    except Exception as e:
        logger.error(f"🔍 [DEBUG] Error in test insert: {e}")
        await db.rollback()
        return {"error": str(e)}

logger.debug("Scheduling router loaded")


# ============================================================================
# Scheduling Proposal System Endpoints
# ============================================================================

@router.post("/proposals", response_model=SchedulingProposalResponse)
async def create_scheduling_proposal(
    proposal_data: SchedulingProposalCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new scheduling proposal with 2-3 time slot options"""
    try:
        # Verify match exists and user is part of it
        match_result = await db.execute(
            select(Match).where(
                Match.id == proposal_data.match_id,
                ((Match.user_id == user.id) | (Match.matched_user_id == user.id))
            )
        )
        match = match_result.scalar_one_or_none()
        if not match:
            raise HTTPException(status_code=404, detail="Match not found or access denied")
        
        # Verify receiver is the other user in the match
        if match.user_id == user.id:
            if match.matched_user_id != proposal_data.receiver_id:
                raise HTTPException(status_code=400, detail="Invalid receiver_id for this match")
        else:
            if match.user_id != proposal_data.receiver_id:
                raise HTTPException(status_code=400, detail="Invalid receiver_id for this match")
        
        # Check for existing pending proposals
        existing_result = await db.execute(
            select(SchedulingProposal).where(
                SchedulingProposal.match_id == proposal_data.match_id,
                SchedulingProposal.status == ProposalStatus.PENDING
            )
        )
        existing_proposal = existing_result.scalar_one_or_none()
        if existing_proposal:
            raise HTTPException(status_code=400, detail="A pending proposal already exists for this match")
        
        # Create proposal with 24-hour expiration
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        proposal = SchedulingProposal(
            match_id=proposal_data.match_id,
            proposer_id=user.id,
            receiver_id=proposal_data.receiver_id,
            status=ProposalStatus.PENDING,
            message=proposal_data.message,
            expires_at=expires_at
        )
        db.add(proposal)
        await db.flush()  # Get the proposal ID
        
        # Create time slots
        for slot_data in proposal_data.time_slots:
            time_slot = ProposalTimeSlot(
                proposal_id=proposal.id,
                start_time=slot_data.start_time,
                end_time=slot_data.end_time,
                is_selected=False
            )
            db.add(time_slot)
        
        await db.commit()
        await db.refresh(proposal)
        
        # Load the proposal with relationships for response
        result = await db.execute(
            select(SchedulingProposal)
            .options(
                selectinload(SchedulingProposal.time_slots),
                selectinload(SchedulingProposal.proposer),
                selectinload(SchedulingProposal.receiver)
            )
            .where(SchedulingProposal.id == proposal.id)
        )
        proposal_with_relations = result.scalar_one()
        
        # S2 — notify the receiver that they have a new proposal to respond to
        try:
            await push.notify_proposal_received(
                recipient=proposal_with_relations.receiver,
                proposer=proposal_with_relations.proposer,
                proposal_id=proposal_with_relations.id,
            )
        except Exception as exc:
            logger.warning(f"[PUSH] S2 notification failed: {exc}")

        return SchedulingProposalResponse(
            id=proposal_with_relations.id,
            match_id=proposal_with_relations.match_id,
            proposer_id=proposal_with_relations.proposer_id,
            receiver_id=proposal_with_relations.receiver_id,
            status=proposal_with_relations.status,
            message=proposal_with_relations.message,
            created_at=proposal_with_relations.created_at,
            expires_at=proposal_with_relations.expires_at,
            responded_at=proposal_with_relations.responded_at,
            proposer_name=proposal_with_relations.proposer.name,
            receiver_name=proposal_with_relations.receiver.name,
            time_slots=[
                {
                    "id": slot.id,
                    "proposal_id": slot.proposal_id,
                    "start_time": slot.start_time,
                    "end_time": slot.end_time,
                    "is_selected": slot.is_selected,
                    "created_at": slot.created_at
                }
                for slot in proposal_with_relations.time_slots
            ]
        )

    except Exception as e:
        logger.error(f"Error creating proposal: {e}")
        await db.rollback()
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Failed to create proposal")

@router.get("/proposals", response_model=ProposalListResponse)
async def get_user_proposals(
    status: Optional[ProposalStatus] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get proposals for the current user (both sent and received)"""
    try:
        # Build query for proposals where user is proposer or receiver
        query = select(SchedulingProposal).options(
            selectinload(SchedulingProposal.time_slots),
            selectinload(SchedulingProposal.proposer),
            selectinload(SchedulingProposal.receiver)
        ).where(
            (SchedulingProposal.proposer_id == user.id) |
            (SchedulingProposal.receiver_id == user.id)
        )
        
        if status:
            query = query.where(SchedulingProposal.status == status)
        
        # Order by created_at descending
        query = query.order_by(SchedulingProposal.created_at.desc())
        
        result = await db.execute(query)
        proposals = result.scalars().all()
        
        # Count proposals by status
        pending_count = len([p for p in proposals if p.status == ProposalStatus.PENDING])
        responded_count = len([p for p in proposals if p.status != ProposalStatus.PENDING])
        
        proposal_responses = []
        for proposal in proposals:
            proposal_responses.append(SchedulingProposalResponse(
                id=proposal.id,
                match_id=proposal.match_id,
                proposer_id=proposal.proposer_id,
                receiver_id=proposal.receiver_id,
                status=proposal.status,
                message=proposal.message,
                created_at=proposal.created_at,
                expires_at=proposal.expires_at,
                responded_at=proposal.responded_at,
                proposer_name=proposal.proposer.name,
                receiver_name=proposal.receiver.name,
                time_slots=[
                    {
                        "id": slot.id,
                        "proposal_id": slot.proposal_id,
                        "start_time": slot.start_time,
                        "end_time": slot.end_time,
                        "is_selected": slot.is_selected,
                        "created_at": slot.created_at
                    }
                    for slot in proposal.time_slots
                ]
            ))
        
        return ProposalListResponse(
            proposals=proposal_responses,
            total_count=len(proposals),
            pending_count=pending_count,
            responded_count=responded_count
        )
        
    except Exception as e:
        logger.error(f"Error getting proposals: {e}")
        raise HTTPException(status_code=500, detail="Failed to get proposals")

@router.get("/proposals/{proposal_id}", response_model=SchedulingProposalResponse)
async def get_proposal(
    proposal_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific proposal by ID"""
    try:
        result = await db.execute(
            select(SchedulingProposal)
            .options(
                selectinload(SchedulingProposal.time_slots),
                selectinload(SchedulingProposal.proposer),
                selectinload(SchedulingProposal.receiver)
            )
            .where(
                SchedulingProposal.id == proposal_id,
                ((SchedulingProposal.proposer_id == user.id) | (SchedulingProposal.receiver_id == user.id))
            )
        )
        proposal = result.scalar_one_or_none()
        
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found or access denied")
        
        return SchedulingProposalResponse(
            id=proposal.id,
            match_id=proposal.match_id,
            proposer_id=proposal.proposer_id,
            receiver_id=proposal.receiver_id,
            status=proposal.status,
            message=proposal.message,
            created_at=proposal.created_at,
            expires_at=proposal.expires_at,
            responded_at=proposal.responded_at,
            proposer_name=proposal.proposer.name,
            receiver_name=proposal.receiver.name,
            time_slots=[
                {
                    "id": slot.id,
                    "proposal_id": slot.proposal_id,
                    "start_time": slot.start_time,
                    "end_time": slot.end_time,
                    "is_selected": slot.is_selected,
                    "created_at": slot.created_at
                }
                for slot in proposal.time_slots
            ]
        )
        
    except Exception as e:
        logger.error(f"Error getting proposal {proposal_id}: {e}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Failed to get proposal")

@router.post("/proposals/{proposal_id}/respond", response_model=ScheduledCallFromProposal)
async def respond_to_proposal(
    proposal_id: int,
    response_data: ProposalResponseCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Respond to a scheduling proposal (accept/reject/counter-propose)"""
    try:
        # Get the proposal
        result = await db.execute(
            select(SchedulingProposal)
            .options(
                selectinload(SchedulingProposal.time_slots),
                selectinload(SchedulingProposal.proposer),
                selectinload(SchedulingProposal.receiver)
            )
            .where(SchedulingProposal.id == proposal_id)
        )
        proposal = result.scalar_one_or_none()
        
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")
        
        # Verify user is the receiver
        if proposal.receiver_id != user.id:
            raise HTTPException(status_code=403, detail="Only the proposal receiver can respond")
        
        # Check if proposal is still pending
        if proposal.status != ProposalStatus.PENDING:
            raise HTTPException(status_code=400, detail="Proposal is no longer pending")
        
        # Check if proposal has expired
        if datetime.now(timezone.utc) > proposal.expires_at:
            proposal.status = ProposalStatus.EXPIRED
            await db.commit()
            raise HTTPException(status_code=400, detail="Proposal has expired")
        
        # Create the response
        proposal_response = ProposalResponse(
            proposal_id=proposal.id,
            response_type=response_data.response_type,
            selected_slot_id=response_data.selected_slot_id,
            counter_proposal_message=response_data.counter_proposal_message
        )
        db.add(proposal_response)
        await db.flush()  # Get the response ID
        
        # Handle different response types
        if response_data.response_type == ProposalResponseType.ACCEPT:
            # Mark the selected slot and update proposal status
            selected_slot_result = await db.execute(
                select(ProposalTimeSlot).where(ProposalTimeSlot.id == response_data.selected_slot_id)
            )
            selected_slot = selected_slot_result.scalar_one()
            selected_slot.is_selected = True

            proposal.status = ProposalStatus.ACCEPTED
            proposal.responded_at = datetime.now(timezone.utc)
            
            # Create a scheduled call
            scheduled_call = ScheduledCall(
                match_id=proposal.match_id,
                user1_id=proposal.proposer_id,
                user2_id=proposal.receiver_id,
                scheduled_start_utc=selected_slot.start_time,
                scheduled_end_utc=selected_slot.end_time,
                duration_minutes=15,  # Fixed 15-minute calls
                status="scheduled"
            )
            db.add(scheduled_call)
            await db.commit()
            await db.refresh(scheduled_call)

            # Update match_outcomes funnel: stamp call_scheduled_at (best-effort)
            try:
                outcome_q = await db.execute(
                    select(MatchOutcome).where(MatchOutcome.match_id == scheduled_call.match_id)
                )
                outcome = outcome_q.scalar_one_or_none()
                if outcome and outcome.call_scheduled_at is None:
                    outcome.call_scheduled_at = datetime.now(timezone.utc)
                    await db.commit()
            except Exception as exc:
                logger.warning(f"Failed to update match_outcomes.call_scheduled_at on proposal accept: {exc}")

            # S3 — notify the proposer that their proposal was accepted
            try:
                await push.notify_proposal_accepted(
                    proposer=proposal.proposer,
                    accepter=proposal.receiver,
                    call_id=scheduled_call.id,
                )
            except Exception as exc:
                logger.warning(f"[PUSH] S3 notification failed: {exc}")

            # Return the scheduled call with proposal details
            return ScheduledCallFromProposal(
                call=ScheduledCallResponse(
                    id=scheduled_call.id,
                    user_id=user.id,
                    match_id=scheduled_call.match_id,
                    user1_id=scheduled_call.user1_id,
                    user2_id=scheduled_call.user2_id,
                    other_user_name=proposal.proposer.name,
                    other_user_id=proposal.proposer_id,
                    start_time_utc=selected_slot.start_time.isoformat() + 'Z',
                    end_time_utc=selected_slot.end_time.isoformat() + 'Z',
                    scheduled_start_utc=scheduled_call.scheduled_start_utc,
                    scheduled_end_utc=scheduled_call.scheduled_end_utc,
                    duration_minutes=scheduled_call.duration_minutes,
                    status=scheduled_call.status,
                    user1_confirmed=scheduled_call.user1_confirmed,
                    user2_confirmed=scheduled_call.user2_confirmed,
                    user1_confirmed_at=scheduled_call.user1_confirmed_at,
                    user2_confirmed_at=scheduled_call.user2_confirmed_at,
                    call_room_id=scheduled_call.call_room_id,
                    call_started_at=scheduled_call.call_started_at,
                    call_ended_at=scheduled_call.call_ended_at,
                    actual_duration_minutes=scheduled_call.actual_duration_minutes,
                    original_call_id=scheduled_call.original_call_id,
                    reschedule_count=scheduled_call.reschedule_count,
                    user1_notified=scheduled_call.user1_notified,
                    user2_notified=scheduled_call.user2_notified,
                    reminder_sent=scheduled_call.reminder_sent,
                    created_at=scheduled_call.created_at,
                    updated_at=scheduled_call.updated_at
                ),
                proposal=SchedulingProposalResponse(
                    id=proposal.id,
                    match_id=proposal.match_id,
                    proposer_id=proposal.proposer_id,
                    receiver_id=proposal.receiver_id,
                    status=proposal.status,
                    message=proposal.message,
                    created_at=proposal.created_at,
                    expires_at=proposal.expires_at,
                    responded_at=proposal.responded_at,
                    proposer_name=proposal.proposer.name,
                    receiver_name=proposal.receiver.name,
                    time_slots=[
                        {
                            "id": slot.id,
                            "proposal_id": slot.proposal_id,
                            "start_time": slot.start_time,
                            "end_time": slot.end_time,
                            "is_selected": slot.is_selected,
                            "created_at": slot.created_at
                        }
                        for slot in proposal.time_slots
                    ]
                )
            )
            
        elif response_data.response_type == ProposalResponseType.REJECT:
            proposal.status = ProposalStatus.REJECTED
            proposal.responded_at = datetime.now(timezone.utc)
            await db.commit()

            # S4 — notify the proposer that their proposal was rejected
            try:
                await push.notify_proposal_rejected(
                    proposer=proposal.proposer, rejecter=proposal.receiver
                )
            except Exception as exc:
                logger.warning(f"[PUSH] S4 notification failed: {exc}")

        elif response_data.response_type == ProposalResponseType.COUNTER_PROPOSE:
            # Add counter proposal time slots
            if response_data.counter_time_slots:
                for counter_slot_data in response_data.counter_time_slots:
                    counter_slot = CounterProposalTimeSlot(
                        response_id=proposal_response.id,
                        start_time=counter_slot_data.start_time,
                        end_time=counter_slot_data.end_time
                    )
                    db.add(counter_slot)

            proposal.status = ProposalStatus.COUNTER_PROPOSED
            proposal.responded_at = datetime.now(timezone.utc)
            await db.commit()

            # S9 — notify the original proposer of the counter-proposal
            try:
                await push.notify_counter_proposal_received(
                    recipient=proposal.proposer,
                    proposer=proposal.receiver,
                    proposal_id=proposal.id,
                )
            except Exception as exc:
                logger.warning(f"[PUSH] S9 notification failed: {exc}")
        
        # For reject and counter-propose, return empty call but with proposal details
        return ScheduledCallFromProposal(
            call=None,
            proposal=SchedulingProposalResponse(
                id=proposal.id,
                match_id=proposal.match_id,
                proposer_id=proposal.proposer_id,
                receiver_id=proposal.receiver_id,
                status=proposal.status,
                message=proposal.message,
                created_at=proposal.created_at,
                expires_at=proposal.expires_at,
                responded_at=proposal.responded_at,
                proposer_name=proposal.proposer.name,
                receiver_name=proposal.receiver.name,
                time_slots=[
                    {
                        "id": slot.id,
                        "proposal_id": slot.proposal_id,
                        "start_time": slot.start_time,
                        "end_time": slot.end_time,
                        "is_selected": slot.is_selected,
                        "created_at": slot.created_at
                    }
                    for slot in proposal.time_slots
                ]
            ),
            message=f"Proposal {response_data.response_type.value}ed successfully"
        )
        
    except Exception as e:
        logger.error(f"Error responding to proposal {proposal_id}: {e}")
        await db.rollback()
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Failed to respond to proposal")


# ============================================================================
# TIER 1 — SPONTANEOUS CALL REQUESTS (post-match 5-minute window)
# ============================================================================

@router.post("/call-requests", response_model=dict)
async def create_call_request(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    User B (the one whose swipe triggered the match) sends a live call request
    to User A.  Expires automatically after 5 minutes.
    """
    from app.models import CallRequest, Match
    from app.schemas import CallRequestCreate
    from datetime import timedelta

    match_id = body.get("match_id")
    if not match_id:
        raise HTTPException(status_code=422, detail="match_id required")

    # Verify the match exists and the caller is a participant
    match_result = await db.execute(
        select(Match).where(
            Match.id == match_id,
            ((Match.user_id == user.id) | (Match.matched_user_id == user.id)),
        )
    )
    match = match_result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found or you are not a participant")

    # Determine recipient (the other person in the match)
    recipient_id = match.matched_user_id if match.user_id == user.id else match.user_id

    # Only allow one pending request per match at a time
    existing = await db.execute(
        select(CallRequest).where(
            CallRequest.match_id == match_id,
            CallRequest.status == "pending",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A pending call request already exists for this match")

    now = datetime.now(timezone.utc)
    call_request = CallRequest(
        match_id=match_id,
        requester_id=user.id,
        recipient_id=recipient_id,
        status="pending",
        expires_at=now + timedelta(minutes=5),
    )
    db.add(call_request)
    await db.commit()
    await db.refresh(call_request)

    logger.info(f"call_request {call_request.id}: created by user {user.id} for match {match_id}")
    return {"id": call_request.id, "expires_at": call_request.expires_at.isoformat(), "status": "pending"}


@router.get("/call-requests/incoming", response_model=list)
async def get_incoming_call_requests(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    User A polls this to find pending call requests addressed to them.
    Auto-expires stale requests at read time.
    """
    from app.models import CallRequest

    now = datetime.now(timezone.utc)

    # Auto-expire any overdue pending requests
    overdue = await db.execute(
        select(CallRequest).where(
            CallRequest.recipient_id == user.id,
            CallRequest.status == "pending",
            CallRequest.expires_at < now,
        )
    )
    for req in overdue.scalars().all():
        req.status = "expired"
    await db.commit()

    # Return remaining live pending requests
    result = await db.execute(
        select(CallRequest).where(
            CallRequest.recipient_id == user.id,
            CallRequest.status == "pending",
        )
    )
    requests = result.scalars().all()

    output = []
    for req in requests:
        requester_result = await db.execute(select(User).where(User.id == req.requester_id))
        requester = requester_result.scalar_one_or_none()
        output.append({
            "id": req.id,
            "match_id": req.match_id,
            "status": req.status,
            "expires_at": req.expires_at.isoformat(),
            "requester": {
                "id": requester.id if requester else req.requester_id,
                "name": requester.name if requester else "Unknown",
                "profile_image_url": requester.profile_image_url if requester else None,
                "firebase_uid": requester.firebase_uid if requester else "",
            },
        })
    return output


@router.get("/call-requests/{request_id}", response_model=dict)
async def get_call_request_status(
    request_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    User B polls this to check whether User A has accepted/declined.
    Also auto-expires at read time and returns room_name when accepted.
    """
    from app.models import CallRequest

    result = await db.execute(select(CallRequest).where(CallRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Call request not found")
    if req.requester_id != user.id and req.recipient_id != user.id:
        raise HTTPException(status_code=403, detail="Not your call request")

    # Auto-expire if overdue
    now = datetime.now(timezone.utc)
    if req.status == "pending" and req.expires_at < now:
        req.status = "expired"
        await db.commit()

    return {
        "id": req.id,
        "match_id": req.match_id,
        "status": req.status,
        "room_name": req.room_name,
        "expires_at": req.expires_at.isoformat(),
    }


@router.post("/call-requests/{request_id}/accept", response_model=dict)
async def accept_call_request(
    request_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User A accepts the call request. Returns the Twilio room name both clients should join."""
    from app.models import CallRequest

    result = await db.execute(select(CallRequest).where(CallRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Call request not found")
    if req.recipient_id != user.id:
        raise HTTPException(status_code=403, detail="Only the recipient can accept")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"Request is already {req.status}")

    now = datetime.now(timezone.utc)
    if req.expires_at < now:
        req.status = "expired"
        await db.commit()
        raise HTTPException(status_code=410, detail="Call request has expired")

    room_name = f"tier1-{request_id}"
    req.status = "accepted"
    req.room_name = room_name
    await db.commit()

    logger.info(f"call_request {request_id}: accepted by user {user.id}, room={room_name}")
    return {"id": req.id, "status": "accepted", "room_name": room_name}


@router.post("/call-requests/{request_id}/decline", response_model=dict)
async def decline_call_request(
    request_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User A declines the call request."""
    from app.models import CallRequest

    result = await db.execute(select(CallRequest).where(CallRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Call request not found")
    if req.recipient_id != user.id:
        raise HTTPException(status_code=403, detail="Only the recipient can decline")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"Request is already {req.status}")

    req.status = "declined"
    await db.commit()

    logger.info(f"call_request {request_id}: declined by user {user.id}")
    return {"id": req.id, "status": "declined"}


# ============================================================================
# ADMIN / TESTING UTILITIES
# ============================================================================

@router.post("/admin/set-all-available")
async def set_all_users_available_24_7(
    db: AsyncSession = Depends(get_db)
):
    """
    Testing utility: sets every user's default availability to 24/7.

    Replaces all rows in user_default_availability with is_available=True
    for every (day_of_week 0-6, hour 0-23, minute 0 or 30) combination,
    and clears any per-week overrides so the defaults are always used.

    The common-availability SQL functions read from user_default_availability
    first (falling back to override), so after this call any two matched users
    will always have common slots available for scheduling.
    """
    from app.models import UserDefaultAvailability, UserAvailabilityOverride
    from sqlalchemy import delete

    # Load all user IDs
    result = await db.execute(select(User.id))
    user_ids = [row[0] for row in result.fetchall()]

    if not user_ids:
        return {"message": "No users found", "users_updated": 0}

    # Wipe existing default and override availability for all users
    await db.execute(
        delete(UserDefaultAvailability).where(UserDefaultAvailability.user_id.in_(user_ids))
    )
    await db.execute(
        delete(UserAvailabilityOverride).where(UserAvailabilityOverride.user_id.in_(user_ids))
    )

    # Bulk-insert 336 slots (7 days × 24 hours × 2 half-hours) per user
    slots = []
    for user_id in user_ids:
        for day in range(7):        # 0=Sunday … 6=Saturday
            for hour in range(24):
                for minute in (0, 30):
                    slots.append(
                        UserDefaultAvailability(
                            user_id=user_id,
                            day_of_week=day,
                            hour=hour,
                            minute=minute,
                            is_available=True,
                        )
                    )

    db.add_all(slots)
    await db.commit()

    logger.info(
        f"set-all-available: inserted {len(slots)} availability slots "
        f"for {len(user_ids)} users"
    )
    return {
        "message": "All users set to 24/7 available",
        "users_updated": len(user_ids),
        "slots_inserted": len(slots),
    }