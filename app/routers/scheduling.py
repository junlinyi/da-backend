# app/routers/scheduling.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime, time, date, timedelta
import pytz
from app.database import get_db
from app.models import (
    User, UserWeeklyAvailability, UserAvailabilityOverride, 
    UserTimezone, UserSchedulingPreferences, ScheduledCall, Match,
    UserMatchCallPreferences
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
    CallPreferenceUpdate, CallPreferenceResponse
)
from app.dependencies import verify_firebase_token
import logging
import traceback
import firebase_admin
from firebase_admin import auth as firebase_auth

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure Firebase Admin is initialized
if not firebase_admin._apps:
    firebase_admin.initialize_app()

router = APIRouter()

# Helper function to get user by Firebase UID, with on-demand creation
async def get_current_user(decoded_token=Depends(verify_firebase_token), db: AsyncSession = Depends(get_db)):
    firebase_uid = decoded_token["uid"]
    try:
        result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
        user = result.scalars().first()
        if not user:
            logger.warning(f"[USER ON-DEMAND] User {firebase_uid} not found in Postgres. Attempting to fetch from Firebase...")
            try:
                fb_user = firebase_auth.get_user(firebase_uid)
                user = User(
                    firebase_uid=firebase_uid,
                    email=fb_user.email,
                    name=fb_user.display_name or None,
                    profile_image_url=fb_user.photo_url or None,
                    is_active=True
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
                logger.info(f"[USER ON-DEMAND] User {firebase_uid} created in Postgres from Firebase.")
            except Exception as e:
                logger.error(f"[USER ON-DEMAND] Failed to fetch/create user {firebase_uid} from Firebase: {e}\n{traceback.format_exc()}")
                raise HTTPException(status_code=404, detail=f"User not found and could not be created: {e}")
        else:
            logger.info(f"[USER FOUND] User {firebase_uid} found in Postgres (ID: {user.id})")
        return user
    except Exception as e:
        logger.error(f"[USER LOOKUP ERROR] Error looking up user {firebase_uid}: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error looking up user: {e}")

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
        call_preference.updated_at = datetime.utcnow()
    
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
        timezone_info.last_updated = datetime.utcnow()
    
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
        preferences.updated_at = datetime.utcnow()
    
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
    """Get user's scheduled calls"""
    query = select(ScheduledCall).where(
        (ScheduledCall.user1_id == user.id) | (ScheduledCall.user2_id == user.id)
    )
    
    if status:
        query = query.where(ScheduledCall.status == status)
    
    if upcoming:
        query = query.where(ScheduledCall.scheduled_start_utc >= datetime.utcnow())
    else:
        query = query.where(ScheduledCall.scheduled_start_utc < datetime.utcnow())
    
    query = query.order_by(ScheduledCall.scheduled_start_utc)
    result = await db.execute(query)
    return result.scalars().all()

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
        return new_call
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
        call.user1_confirmed_at = datetime.utcnow()
    else:
        call.user2_confirmed = True
        call.user2_confirmed_at = datetime.utcnow()
    
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
    call.call_ended_at = datetime.utcnow()
    
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
    # Use the database function to find common availability
    result = await db.execute(
        text("SELECT * FROM find_common_availability(:user1_id, :user2_id, :start_date, :end_date)"),
        {"user1_id": request.user1_id, "user2_id": request.user2_id, "start_date": request.start_date, "end_date": request.end_date}
    )
    common_slots = result.fetchall()
    
    # Convert to response format
    available_slots = []
    for slot in common_slots:
        # Convert date and time to UTC datetime
        slot_start_utc = datetime.combine(slot.date, slot.start_time)
        slot_end_utc = datetime.combine(slot.date, slot.end_time)
        
        available_slots.append({
            "start_time_utc": slot_start_utc,
            "end_time_utc": slot_end_utc,
            "user1_local_time": f"{slot.date} {slot.start_time}",
            "user2_local_time": f"{slot.date} {slot.start_time}"
        })
    
    # Sort by start time and take earliest 3
    available_slots.sort(key=lambda x: x["start_time_utc"])
    available_slots = available_slots[:3]
    
    return FindCommonAvailabilityResponse(
        available_slots=available_slots,
        total_slots_checked=len(common_slots)
    )

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
    """Update user's default availability schedule (iOS app compatibility)"""
    try:
        user_id = request.get("user_id")
        time_slots = request.get("time_slots", [])
        
        # Check if user exists
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Clear existing default availability for this user
        from app.models import UserDefaultAvailability
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
        
        await db.commit()
        logger.info(f"Updated default availability for user {user_id} with {len(unique_slots)} unique time slots (from {len(time_slots)} total)")
        
        return {
            "user_id": user_id,
            "time_slots": list(unique_slots.values())
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
        
        # Convert to When2Meet-style time slots format expected by iOS app
        # Generate ALL possible slots for the 7-day period and populate with override data
        time_slots = []
        
        # Create a lookup for existing override slots
        override_lookup = {}
        for slot in override_slots:
            # Convert date to day_of_week relative to query_start
            days_from_start = (slot.date - query_start).days
            if 0 <= days_from_start < 7:  # Only include slots within our 7-day range
                key = f"{days_from_start}_{slot.start_time.hour}_{slot.start_time.minute}"
                override_lookup[key] = True  # Mark this slot as available
        
        # Generate all possible slots for the 7-day period
        for day_offset in range(7):
            # Calculate day_of_week based on query_start
            current_date = query_start + timedelta(days=day_offset)
            python_weekday = current_date.weekday()  # Monday=0, Sunday=6
            day_of_week = (python_weekday + 1) % 7  # Convert to Sunday=0
            
            for hour in range(24):
                for minute in [0, 30]:
                    slot_id = day_offset * 10000 + hour * 100 + minute
                    key = f"{day_offset}_{hour}_{minute}"
                    is_available = override_lookup.get(key, False)
                    
                    time_slots.append({
                        "id": slot_id,
                        "date": current_date.isoformat(),
                        "start_time": f"{hour:02d}:{minute:02d}",
                        "end_time": f"{hour:02d}:{minute+30:02d}" if minute == 0 else f"{hour+1:02d}:00" if hour < 23 else "23:59",
                        "day_of_week": day_of_week,
                        "hour": hour,
                        "minute": minute,
                        "is_available": is_available,
                        "is_override": True
                    })
        
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
            ScheduledCall.scheduled_start_utc >= datetime.utcnow()
        )
        .order_by(ScheduledCall.scheduled_start_utc)
    )
    upcoming_calls = upcoming_calls_result.scalars().all()
    
    past_calls_result = await db.execute(
        select(ScheduledCall)
        .where(
            (ScheduledCall.user1_id == user.id) | (ScheduledCall.user2_id == user.id),
            ScheduledCall.scheduled_start_utc < datetime.utcnow()
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

print("🔍 [DEBUG] Scheduling router loaded successfully - debug endpoint should be available")