# app/schemas.py

from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime, time, date, timezone
from enum import Enum
import json

# Enums to match frontend
class Gender(str, Enum):
    male = "male"
    female = "female"
    nonBinary = "nonBinary"
    other = "other"

# Location structure to match frontend
class Location(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)

# TimeSlot structure to match frontend
class TimeSlot(BaseModel):
    startTime: datetime
    endTime: datetime
    isAvailable: bool

# Comprehensive User schema that matches frontend
class UserResponse(BaseModel):
    id: int
    firebase_uid: str
    email: str
    name: str
    age: Optional[int] = None
    bio: Optional[str] = None
    gender: Optional[str] = None
    interests: Optional[List[str]] = None
    profile_image_url: Optional[str] = None
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    state: Optional[str] = None
    preferred_gender: Optional[str] = None
    min_age_preference: Optional[int] = None
    max_age_preference: Optional[int] = None
    max_distance_km: Optional[int] = None
    additional_image_urls: Optional[List[str]] = None
    timezone: Optional[str] = None
    is_active: Optional[bool] = None
    last_active: Optional[datetime] = None
    profile_completed: Optional[bool] = None
    is_verified: Optional[bool] = None
    strikes: Optional[int] = None
    prompts: Optional[List[dict]] = None

# Profile update schema - used by iOS app for /me/profile endpoint
class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None
    age: Optional[int] = Field(None, ge=18, le=100)
    gender: Optional[Gender] = None
    interests: Optional[List[str]] = None
    location: Optional[Location] = None
    profileImageURL: Optional[str] = None
    prompts: Optional[List[dict]] = None

# Preferences update schema - used by iOS app for /me/preferences endpoint
class PreferencesUpdate(BaseModel):
    preferredGender: Gender
    minAgePreference: int = Field(..., ge=18, le=100)
    maxAgePreference: int = Field(..., ge=18, le=100)
    
    @validator('maxAgePreference')
    def max_age_must_be_greater_than_min(cls, v, values):
        if 'minAgePreference' in values and v <= values['minAgePreference']:
            raise ValueError('maxAgePreference must be greater than minAgePreference')
        return v

# UserUpdate schema - used for admin/external API endpoints
# This is NOT used by the iOS app, but by:
# - Admin interfaces to update any user's profile
# - External services that need to update user data
# - Backend sync services
# - PUT /{user_id} endpoint (not /me/profile)
class UserUpdate(BaseModel):
    """
    Schema for updating any user's complete profile.
    
    This is used by admin endpoints and external services, NOT by the iOS app.
    The iOS app uses ProfileUpdate and PreferencesUpdate separately.
    
    Usage:
    - PUT /{user_id} - Update any user by their ID
    - Admin interfaces
    - Backend sync services
    - External API consumers
    """
    name: Optional[str] = None
    bio: Optional[str] = None
    age: Optional[int] = Field(None, ge=18, le=100)
    gender: Optional[Gender] = None
    interests: Optional[List[str]] = None
    location: Optional[Location] = None
    preferredGender: Optional[Gender] = None
    minAgePreference: Optional[int] = Field(None, ge=18, le=100)
    maxAgePreference: Optional[int] = Field(None, ge=18, le=100)
    profileImageURL: Optional[str] = None
    isVerified: Optional[bool] = None
    strikes: Optional[int] = Field(None, ge=0)
    
    @validator('maxAgePreference')
    def max_age_must_be_greater_than_min(cls, v, values):
        if v is not None and 'minAgePreference' in values and values['minAgePreference'] is not None:
            if v <= values['minAgePreference']:
                raise ValueError('maxAgePreference must be greater than minAgePreference')
        return v

# Legacy schemas for backward compatibility
class UserCreate(BaseModel):
    email: EmailStr

class SwipeCreate(BaseModel):
    swiped_firebase_uid: str  # Changed from swiped_id: int to use Firebase UIDs
    liked: bool

# Messaging schemas
_ALLOWED_MESSAGE_TYPES = {"text", "image", "video", "audio", "file"}

class MessageCreate(BaseModel):
    content: str = Field(..., max_length=5000)
    message_type: Optional[str] = "text"

    @validator('message_type')
    def validate_message_type(cls, v):
        if v is not None and v not in _ALLOWED_MESSAGE_TYPES:
            raise ValueError(f'message_type must be one of: {", ".join(sorted(_ALLOWED_MESSAGE_TYPES))}')
        return v

class MessageResponse(BaseModel):
    id: int
    sender_id: int
    content: str
    timestamp: datetime
    message_type: str

class ConversationResponse(BaseModel):
    id: int
    other_user_id: str  # Firebase UID
    other_user_name: str
    other_user_profile_image: Optional[str] = None
    last_message: Optional[str] = None
    last_message_at: Optional[datetime] = None
    unread_count: int = 0
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() + 'Z' if v else None
        }

# Video Call Scheduling Schemas

class UserWeeklyAvailabilityCreate(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)  # 0=Sunday, 6=Saturday
    start_time: time
    end_time: time
    
    @validator('end_time')
    def end_time_must_be_after_start_time(cls, v, values):
        if 'start_time' in values and v <= values['start_time']:
            raise ValueError('end_time must be after start_time')
        return v

class UserWeeklyAvailabilityResponse(BaseModel):
    id: int
    user_id: int
    day_of_week: int
    start_time: time
    end_time: time
    created_at: datetime
    updated_at: datetime

class UserAvailabilityOverrideCreate(BaseModel):
    date: date
    start_time: time
    end_time: time
    reason: Optional[str] = None
    
    @validator('end_time')
    def end_time_must_be_after_start_time(cls, v, values):
        if 'start_time' in values and v <= values['start_time']:
            raise ValueError('end_time must be after start_time')
        return v

class UserAvailabilityOverrideResponse(BaseModel):
    id: int
    user_id: int
    date: date
    start_time: time
    end_time: time
    reason: Optional[str]
    created_at: datetime

class UserTimezoneCreate(BaseModel):
    timezone: str = "UTC"  # e.g., 'America/New_York'
    timezone_offset: int = 0  # Offset in minutes from UTC
    dst_enabled: bool = False

class UserTimezoneResponse(BaseModel):
    id: int
    user_id: int
    timezone: str
    timezone_offset: int
    dst_enabled: bool
    last_updated: datetime

class ScheduledCallCreate(BaseModel):
    match_id: int
    user1_id: int
    user2_id: int
    scheduled_start_utc: datetime
    scheduled_end_utc: datetime
    duration_minutes: int = Field(15, ge=5, le=60)
    
    @validator('scheduled_end_utc')
    def end_time_must_be_after_start_time(cls, v, values):
        if 'scheduled_start_utc' in values and v <= values['scheduled_start_utc']:
            raise ValueError('scheduled_end_utc must be after scheduled_start_utc')
        return v

class ScheduledCallResponse(BaseModel):
    id: int
    match_id: int
    user1_id: int
    user2_id: int
    scheduled_start_utc: datetime
    scheduled_end_utc: datetime
    duration_minutes: int
    status: str
    user1_confirmed: bool
    user2_confirmed: bool
    user1_confirmed_at: Optional[datetime]
    user2_confirmed_at: Optional[datetime]
    call_room_id: Optional[str]
    call_started_at: Optional[datetime]
    call_ended_at: Optional[datetime]
    actual_duration_minutes: Optional[int]
    original_call_id: Optional[int]
    reschedule_count: int
    user1_notified: bool
    user2_notified: bool
    reminder_sent: bool
    created_at: datetime
    updated_at: datetime

class CallRatingCreate(BaseModel):
    call_id: int
    rater_id: int
    rated_user_id: int
    rating: int = Field(..., ge=1, le=5)
    feedback: Optional[str] = None
    categories: Optional[List[str]] = None

class CallRatingResponse(BaseModel):
    id: int
    call_id: int
    rater_id: int
    rated_user_id: int
    rating: int
    feedback: Optional[str]
    categories: Optional[List[str]]
    created_at: datetime

class UserSchedulingPreferenceCreate(BaseModel):
    # Fixed 15-minute calls - extensions handled during call
    max_calls_per_week: int = Field(5, ge=1, le=20)
    min_notice_hours: int = Field(2, ge=0, le=168)  # Minimum notice required
    max_advance_days: int = Field(7, ge=1, le=30)  # How far in advance to schedule
    preferred_start_time: time = time(18, 0, 0)  # 6 PM
    preferred_end_time: time = time(22, 0, 0)  # 10 PM
    email_notifications: bool = True
    push_notifications: bool = True
    reminder_hours_before: int = Field(1, ge=0, le=24)
    
    @validator('preferred_end_time')
    def end_time_must_be_after_start_time(cls, v, values):
        if 'preferred_start_time' in values and v <= values['preferred_start_time']:
            raise ValueError('preferred_end_time must be after preferred_start_time')
        return v

class UserSchedulingPreferenceResponse(BaseModel):
    id: int
    user_id: int
    # preferred_call_duration is fixed at 15 minutes
    max_calls_per_week: int
    min_notice_hours: int
    max_advance_days: int
    preferred_start_time: time
    preferred_end_time: time
    email_notifications: bool
    push_notifications: bool
    reminder_hours_before: int
    created_at: datetime
    updated_at: datetime

# Availability checking schemas
class AvailabilityCheckRequest(BaseModel):
    user1_id: int
    user2_id: int
    start_date: date
    end_date: date
    duration_minutes: int = 15

class AvailabilitySlot(BaseModel):
    start_time: datetime  # UTC time
    end_time: datetime    # UTC time
    user1_available: bool
    user2_available: bool

class AvailabilityCheckResponse(BaseModel):
    user1_id: int
    user2_id: int
    available_slots: List[AvailabilitySlot]
    timezone_info: dict  # Timezone info for both users

class UserBase(BaseModel):
    email: EmailStr
    name: Optional[str] = Field(None, max_length=100)
    bio: Optional[str] = Field(None, max_length=1000)
    age: Optional[int] = Field(None, ge=18, le=120)
    gender: Optional[str] = None
    interests: Optional[List[str]] = None
    location: Optional[str] = Field(None, max_length=200)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    state: Optional[str] = Field(None, max_length=100)
    preferred_gender: Optional[str] = None
    min_age_preference: Optional[int] = Field(18, ge=18, le=120)
    max_age_preference: Optional[int] = Field(120, ge=18, le=120)
    max_distance_km: Optional[int] = Field(32, ge=1, le=20000)
    profile_image_url: Optional[str] = None
    additional_image_urls: Optional[List[str]] = None
    is_verified: bool = False
    strikes: int = Field(0, ge=0)
    timezone: str = "UTC"

class UserCreate(UserBase):
    firebase_uid: str

class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    bio: Optional[str] = Field(None, max_length=1000)
    age: Optional[int] = Field(None, ge=18, le=120)
    gender: Optional[str] = None
    interests: Optional[List[str]] = None
    location: Optional[str] = Field(None, max_length=200)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    state: Optional[str] = Field(None, max_length=100)
    preferred_gender: Optional[str] = None
    min_age_preference: Optional[int] = Field(None, ge=18, le=120)
    max_age_preference: Optional[int] = Field(None, ge=18, le=120)
    max_distance_km: Optional[int] = Field(None, ge=1, le=20000)
    profile_image_url: Optional[str] = None
    additional_image_urls: Optional[List[str]] = None
    timezone: Optional[str] = None

class User(UserBase):
    id: int
    firebase_uid: str
    is_active: bool
    profile_completed: bool
    last_active: datetime

    class Config:
        from_attributes = True

class MatchBase(BaseModel):
    user_id: int
    matched_user_id: int
    match_score: Optional[float] = None
    status: str = "pending"

class MatchCreate(MatchBase):
    pass

class Match(MatchBase):
    id: int
    created_at: datetime
    last_updated: datetime
    user1_last_active: datetime
    user2_last_active: datetime
    user1_unread_count: int
    user2_unread_count: int
    user1_status: str
    user2_status: str

    class Config:
        from_attributes = True

class SwipeBase(BaseModel):
    swiper_id: int
    swiped_id: int
    liked: bool = False
    match_score: Optional[float] = None

# SwipeCreate is defined above at line 121 with Firebase UID support
# This duplicate definition is removed to avoid confusion

class Swipe(SwipeBase):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True

class ConversationBase(BaseModel):
    user1_id: int
    user2_id: int
    last_message: Optional[str] = None
    user1_unread_count: int = 0
    user2_unread_count: int = 0
    is_active: bool = True

class ConversationCreate(ConversationBase):
    pass

class Conversation(ConversationBase):
    id: int
    created_at: datetime
    last_message_at: datetime

    class Config:
        from_attributes = True

class MessageBase(BaseModel):
    conversation_id: int
    sender_id: int
    content: str
    message_type: str = "text"
    is_read: bool = False
    firebase_id: Optional[str] = None

class MessageCreate(MessageBase):
    pass

class Message(MessageBase):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True

# Video Call Scheduling Schemas

class TimeSlot(BaseModel):
    start_time: time
    end_time: time
    is_available: bool = True

    @validator('end_time')
    def end_time_must_be_after_start_time(cls, v, values):
        if 'start_time' in values and v <= values['start_time']:
            raise ValueError('end_time must be after start_time')
        return v

class WeeklyAvailabilitySlot(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)  # 0=Sunday, 6=Saturday
    start_time: time
    end_time: time
    is_available: bool = True

    @validator('end_time')
    def end_time_must_be_after_start_time(cls, v, values):
        if 'start_time' in values and v <= values['start_time']:
            raise ValueError('end_time must be after start_time')
        return v

class WeeklyAvailabilityCreate(BaseModel):
    slots: List[WeeklyAvailabilitySlot]

class WeeklyAvailabilityUpdate(BaseModel):
    slots: List[WeeklyAvailabilitySlot]

class WeeklyAvailabilityResponse(BaseModel):
    user_id: int
    slots: List[WeeklyAvailabilitySlot]

    class Config:
        from_attributes = True

class AvailabilityOverrideCreate(BaseModel):
    date: date
    start_time: time
    end_time: time
    is_available: bool = True
    override_type: str = "override"  # "override", "block"
    reason: Optional[str] = None

    @validator('end_time')
    def end_time_must_be_after_start_time(cls, v, values):
        if 'start_time' in values and v <= values['start_time']:
            raise ValueError('end_time must be after start_time')
        return v

    @validator('date')
    def date_must_be_future(cls, v):
        if v < date.today():
            raise ValueError('date must be in the future')
        return v

class AvailabilityOverrideUpdate(BaseModel):
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    is_available: Optional[bool] = None
    reason: Optional[str] = None

class AvailabilityOverride(AvailabilityOverrideCreate):
    id: int
    user_id: int
    created_at: datetime

    class Config:
        from_attributes = True

class UserTimezoneCreate(BaseModel):
    timezone: str = "UTC"  # e.g., "America/New_York"
    timezone_offset: int = 0  # Offset in minutes from UTC
    dst_enabled: bool = False

class UserTimezoneUpdate(BaseModel):
    timezone: Optional[str] = None
    timezone_offset: Optional[int] = None
    dst_enabled: Optional[bool] = None

class UserTimezone(UserTimezoneCreate):
    id: int
    user_id: int
    last_updated: datetime

    class Config:
        from_attributes = True

class CallStatus(str, Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"

class ScheduledCallCreate(BaseModel):
    match_id: int
    user1_id: int
    user2_id: int
    scheduled_start_utc: datetime
    # Fixed 15-minute calls - extensions handled during call
    duration_minutes: int = 15  # Fixed, cannot be changed

    @validator('duration_minutes')
    def validate_duration(cls, v):
        if v != 15:
            raise ValueError('duration must be exactly 15 minutes - extensions are handled during the call')
        return v

class ScheduledCallUpdate(BaseModel):
    scheduled_start_utc: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    status: Optional[CallStatus] = None
    call_room_id: Optional[str] = None

class ScheduledCallResponse(BaseModel):
    id: int
    user_id: int  # For iOS compatibility
    match_id: int
    user1_id: int
    user2_id: int
    # User names for display
    user1_name: Optional[str] = None
    user2_name: Optional[str] = None
    # Indicate which user is the "other" user from current user's perspective
    other_user_name: Optional[str] = None
    other_user_id: Optional[int] = None
    start_time_utc: str  # iOS expects string format
    end_time_utc: str    # iOS expects string format
    scheduled_start_utc: datetime
    scheduled_end_utc: datetime
    duration_minutes: int
    status: CallStatus
    user1_confirmed: bool
    user2_confirmed: bool
    user1_confirmed_at: Optional[datetime]
    user2_confirmed_at: Optional[datetime]
    call_room_id: Optional[str]
    call_started_at: Optional[datetime]
    call_ended_at: Optional[datetime]
    actual_duration_minutes: Optional[int]
    original_call_id: Optional[int]
    reschedule_count: int
    user1_notified: bool
    user2_notified: bool
    reminder_sent: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class CallConfirmation(BaseModel):
    confirmed: bool = True

class CallRatingCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    feedback: Optional[str] = None
    categories: Optional[List[str]] = None

class CallRatingUpdate(BaseModel):
    rating: Optional[int] = Field(None, ge=1, le=5)
    feedback: Optional[str] = None
    categories: Optional[List[str]] = None

class CallRating(CallRatingCreate):
    id: int
    call_id: int
    rater_id: int
    rated_user_id: int
    created_at: datetime

    class Config:
        from_attributes = True

class SchedulingPreferencesCreate(BaseModel):
    # Fixed 15-minute calls - extensions handled during call
    max_calls_per_week: int = 5
    min_notice_hours: int = 2
    max_advance_days: int = 7
    preferred_start_time: time = time(18, 0)  # 6 PM
    preferred_end_time: time = time(22, 0)  # 10 PM
    email_notifications: bool = True
    push_notifications: bool = True
    reminder_hours_before: int = 1

    @validator('max_calls_per_week')
    def validate_max_calls(cls, v):
        if v < 1 or v > 20:
            raise ValueError('max_calls_per_week must be between 1 and 20')
        return v

    @validator('preferred_end_time')
    def validate_preferred_times(cls, v, values):
        if 'preferred_start_time' in values and v <= values['preferred_start_time']:
            raise ValueError('preferred_end_time must be after preferred_start_time')
        return v

class SchedulingPreferencesUpdate(BaseModel):
    # preferred_call_duration is fixed at 15 minutes - cannot be changed
    max_calls_per_week: Optional[int] = None
    min_notice_hours: Optional[int] = None
    max_advance_days: Optional[int] = None
    preferred_start_time: Optional[time] = None
    preferred_end_time: Optional[time] = None
    email_notifications: Optional[bool] = None
    push_notifications: Optional[bool] = None
    reminder_hours_before: Optional[int] = None

class SchedulingPreferences(SchedulingPreferencesCreate):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Availability checking and scheduling schemas

class AvailabilityCheckRequest(BaseModel):
    user_id: int
    start_time_utc: datetime
    end_time_utc: datetime

class AvailabilityCheckResponse(BaseModel):
    user_id: int
    is_available: bool
    conflicts: List[Dict[str, Any]] = []

class FindCommonAvailabilityRequest(BaseModel):
    user1_id: int
    user2_id: int
    start_date: date
    end_date: date
    duration_minutes: int = 15

class CommonAvailabilitySlot(BaseModel):
    start_time_utc: datetime
    end_time_utc: datetime
    user1_local_time: str  # Formatted local time for user1
    user2_local_time: str  # Formatted local time for user2

class FindCommonAvailabilityResponse(BaseModel):
    available_slots: List[CommonAvailabilitySlot]
    total_slots_checked: int

# API Response schemas

class AvailabilityResponse(BaseModel):
    weekly_availability: WeeklyAvailabilityResponse
    overrides: List[AvailabilityOverride]
    has_upcoming_overrides: bool  # True if user has overrides for next 7 days
    timezone: UserTimezone
    preferences: SchedulingPreferences

class UserScheduleResponse(BaseModel):
    user_id: int
    weekly_availability: List[WeeklyAvailabilitySlot]
    overrides: List[AvailabilityOverride]
    has_upcoming_overrides: bool  # True if user has overrides for next 7 days
    timezone: UserTimezone
    preferences: SchedulingPreferences
    upcoming_calls: List[ScheduledCallResponse]
    past_calls: List[ScheduledCallResponse]

class CallSchedulingResponse(BaseModel):
    call: ScheduledCallResponse
    user1_local_time: str
    user2_local_time: str
    message: str

# ============================================================================
# NEW BATCH SCHEMAS FOR WHEN2MEET STYLE UPDATES
# ============================================================================

class WeeklyAvailabilityBatchCreate(BaseModel):
    slots: List[UserWeeklyAvailabilityCreate]
    
    @validator('slots')
    def validate_slots(cls, v):
        if not v:
            raise ValueError('At least one slot must be provided')
        return v

class WeeklyAvailabilityBatchResponse(BaseModel):
    created_slots: List[UserWeeklyAvailabilityResponse]
    errors: List[str] = []
    total_created: int
    total_errors: int

class AvailabilityOverrideBatchCreate(BaseModel):
    overrides: List[UserAvailabilityOverrideCreate]
    
    @validator('overrides')
    def validate_overrides(cls, v):
        if not v:
            raise ValueError('At least one override must be provided')
        return v

class AvailabilityOverrideBatchResponse(BaseModel):
    created_overrides: List[UserAvailabilityOverrideResponse]
    errors: List[str] = []
    total_created: int
    total_errors: int

# ============================================================================
# CALL PREFERENCE SCHEMAS
# ============================================================================

class CallPreferenceStatus(str, Enum):
    PENDING = "pending"
    WANTS_TO_CALL = "wants_to_call"
    DOESNT_WANT_TO_CALL = "doesnt_want_to_call"
    ALREADY_CALLED = "already_called"

class CallPreferenceUpdate(BaseModel):
    status: CallPreferenceStatus

class CallPreferenceResponse(BaseModel):
    id: int
    user_id: int
    matched_user_id: int
    status: CallPreferenceStatus
    created_at: datetime
    updated_at: datetime
    last_common_availability_check: Optional[datetime] = None
    last_notification_sent: Optional[datetime] = None
    
    class Config:
        from_attributes = True

# ============================================================================
# When2Meet Style Availability Schemas
# ============================================================================

class TimeSlotBase(BaseModel):
    """Base time slot for When2Meet style availability"""
    day_of_week: int = Field(..., ge=0, le=6, description="Day of week (0=Sunday, 6=Saturday)")
    hour: int = Field(..., ge=0, le=23, description="Hour (0-23)")
    minute: int = Field(..., description="Minute (0 or 30 for 30-minute slots)")
    is_available: bool = Field(default=False, description="Whether this time slot is available")

    @validator('minute')
    def validate_minute(cls, v):
        if v not in [0, 30]:
            raise ValueError('Minute must be 0 or 30 for 30-minute slots')
        return v


class DefaultAvailabilitySlot(TimeSlotBase):
    """Default availability time slot"""
    id: Optional[int] = None
    user_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OverrideAvailabilitySlot(TimeSlotBase):
    """Override availability time slot for a specific week"""
    id: Optional[int] = None
    user_id: int
    week_start_date: date = Field(..., description="Start date of the week (Sunday)")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DefaultAvailabilityResponse(BaseModel):
    """Response for default availability"""
    user_id: int
    slots: List[DefaultAvailabilitySlot]
    total_slots: int
    available_slots: int

    class Config:
        from_attributes = True


class OverrideAvailabilityResponse(BaseModel):
    """Response for override availability"""
    user_id: int
    week_start_date: date
    slots: List[OverrideAvailabilitySlot]
    total_slots: int
    available_slots: int

    class Config:
        from_attributes = True


class WeeklyAvailabilityResponse(BaseModel):
    """Response for weekly availability (combines default + overrides)"""
    user_id: int
    week_start_date: date
    slots: List[dict]  # Combined slots with is_override flag
    total_slots: int
    available_slots: int
    default_slots: int
    override_slots: int

    class Config:
        from_attributes = True


class BatchUpdateRequest(BaseModel):
    """Request for batch updating availability slots"""
    slots: List[TimeSlotBase]
    
    @validator('slots')
    def validate_slots(cls, v):
        if not v:
            raise ValueError('At least one slot must be provided')
        return v


class AvailabilitySummary(BaseModel):
    """Summary of user's availability"""
    user_id: int
    total_default_slots: int
    available_default_slots: int
    total_override_slots: int
    available_override_slots: int
    next_available_time: Optional[datetime] = None


# ============================================================================
# Scheduling Proposal System Schemas
# ============================================================================

class ProposalStatus(str, Enum):
    """Status values for scheduling proposals"""
    PENDING = "pending"
    ACCEPTED = "accepted" 
    REJECTED = "rejected"
    COUNTER_PROPOSED = "counter_proposed"
    EXPIRED = "expired"

class ProposalResponseType(str, Enum):
    """Response types for proposal responses"""
    ACCEPT = "accept"
    REJECT = "reject"
    COUNTER_PROPOSE = "counter_propose"

class ProposalTimeSlotCreate(BaseModel):
    """Time slot for proposal creation"""
    start_time: datetime = Field(..., description="Start time in UTC")
    end_time: datetime = Field(..., description="End time in UTC")
    
    @validator('end_time')
    def end_time_must_be_after_start_time(cls, v, values):
        if 'start_time' in values and v <= values['start_time']:
            raise ValueError('end_time must be after start_time')
        return v
    
    @validator('start_time')
    def start_time_must_be_future(cls, v):
        if v <= datetime.now(timezone.utc):
            raise ValueError('start_time must be in the future')
        return v

class ProposalTimeSlotResponse(BaseModel):
    """Time slot response with ID"""
    id: int
    proposal_id: int
    start_time: datetime
    end_time: datetime
    is_selected: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class SchedulingProposalCreate(BaseModel):
    """Create a new scheduling proposal"""
    match_id: int = Field(..., description="Match ID for the proposal")
    receiver_id: int = Field(..., description="User ID of the proposal receiver")
    time_slots: List[ProposalTimeSlotCreate] = Field(..., min_items=2, max_items=3, 
                                                    description="2-3 time slot options")
    message: Optional[str] = Field(None, max_length=500, description="Optional message")
    
    @validator('time_slots')
    def validate_time_slots(cls, v):
        if len(v) < 2:
            raise ValueError('Must provide at least 2 time slot options')
        if len(v) > 3:
            raise ValueError('Cannot provide more than 3 time slot options')
        return v

class SchedulingProposalResponse(BaseModel):
    """Response for scheduling proposal"""
    id: int
    match_id: int
    proposer_id: int
    receiver_id: int
    status: ProposalStatus
    message: Optional[str]
    created_at: datetime
    expires_at: datetime
    responded_at: Optional[datetime]
    
    # Include proposer and receiver names for display
    proposer_name: Optional[str] = None
    receiver_name: Optional[str] = None
    
    # Include time slots
    time_slots: List[ProposalTimeSlotResponse]
    
    class Config:
        from_attributes = True

class CounterProposalTimeSlotCreate(BaseModel):
    """Time slot for counter proposal"""
    start_time: datetime = Field(..., description="Start time in UTC")
    end_time: datetime = Field(..., description="End time in UTC")
    
    @validator('end_time')
    def end_time_must_be_after_start_time(cls, v, values):
        if 'start_time' in values and v <= values['start_time']:
            raise ValueError('end_time must be after start_time')
        return v

class CounterProposalTimeSlotResponse(BaseModel):
    """Counter proposal time slot response"""
    id: int
    response_id: int
    start_time: datetime
    end_time: datetime
    created_at: datetime
    
    class Config:
        from_attributes = True

class ProposalResponseCreate(BaseModel):
    """Create a response to a scheduling proposal"""
    response_type: ProposalResponseType = Field(..., description="Type of response")
    selected_slot_id: Optional[int] = Field(None, description="ID of selected slot (for accepts)")
    counter_proposal_message: Optional[str] = Field(None, max_length=500, 
                                                  description="Message for counter proposals")
    counter_time_slots: Optional[List[CounterProposalTimeSlotCreate]] = Field(None, 
                                                                              description="Time slots for counter proposals")
    
    @validator('selected_slot_id')
    def validate_selected_slot_for_accept(cls, v, values):
        if values.get('response_type') == ProposalResponseType.ACCEPT and v is None:
            raise ValueError('selected_slot_id is required when accepting a proposal')
        if values.get('response_type') != ProposalResponseType.ACCEPT and v is not None:
            raise ValueError('selected_slot_id should only be provided when accepting')
        return v
    
    @validator('counter_time_slots')
    def validate_counter_time_slots(cls, v, values):
        if values.get('response_type') == ProposalResponseType.COUNTER_PROPOSE:
            if not v or len(v) < 2 or len(v) > 3:
                raise ValueError('Counter proposals must include 2-3 time slot options')
        elif v is not None:
            raise ValueError('counter_time_slots should only be provided for counter proposals')
        return v

class ProposalResponseResponse(BaseModel):
    """Response for proposal response"""
    id: int
    proposal_id: int
    response_type: ProposalResponseType
    selected_slot_id: Optional[int]
    counter_proposal_message: Optional[str]
    created_at: datetime
    
    # Include counter proposal time slots if applicable
    counter_time_slots: List[CounterProposalTimeSlotResponse] = []
    
    class Config:
        from_attributes = True

class ProposalListResponse(BaseModel):
    """Response for listing proposals"""
    proposals: List[SchedulingProposalResponse]
    total_count: int
    pending_count: int
    responded_count: int

class ScheduledCallFromProposal(BaseModel):
    """Response when a proposal is accepted and converted to a scheduled call"""
    call: ScheduledCallResponse
    proposal: SchedulingProposalResponse
    message: str = "Proposal accepted and call scheduled successfully"


# ============================================================================
# Video Call Room Schemas
# ============================================================================

class VideoCallTokenRequest(BaseModel):
    """Request for generating a Twilio access token"""
    room_name: str = Field(..., description="Name of the room to join")
    user_identity: str = Field(..., description="Unique identifier for the user")
    
    class Config:
        from_attributes = True

class VideoCallTokenResponse(BaseModel):
    """Response containing Twilio access token"""
    token: str = Field(..., description="Twilio access token")
    room_name: str = Field(..., description="Name of the room")
    
    class Config:
        from_attributes = True

class VideoCallRoomRequest(BaseModel):
    """Request for creating or getting a video call room"""
    call_id: int = Field(..., description="ID of the scheduled call")
    
    class Config:
        from_attributes = True

class VideoCallRoomResponse(BaseModel):
    """Response for video call room creation/retrieval"""
    room_name: str = Field(..., description="Name of the room")
    room_sid: Optional[str] = Field(None, description="Twilio room SID")
    status: str = Field(..., description="Room status: active, ended, or expired")
    
    class Config:
        from_attributes = True

class VideoCallRoomStatusResponse(BaseModel):
    """Response for video call room status"""
    room_name: str = Field(..., description="Name of the room")
    room_sid: Optional[str] = Field(None, description="Twilio room SID")
    status: str = Field(..., description="Room status: active, ended, or expired")
    created_at: datetime = Field(..., description="When the room was created")
    ended_at: Optional[datetime] = Field(None, description="When the room was ended")
    
    class Config:
        from_attributes = True
