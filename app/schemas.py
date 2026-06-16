# app/schemas.py

from pydantic import BaseModel, ConfigDict, EmailStr, Field, validator
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
    model_config = ConfigDict(from_attributes=True)

    id: int
    firebase_uid: str
    email: Optional[str] = None
    phone_number: Optional[str] = None
    name: Optional[str] = None
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
    is_admin: Optional[bool] = None
    prompts: Optional[List[dict]] = None

# Profile update schema - used by iOS app for /me/profile endpoint
class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    bio: Optional[str] = Field(None, max_length=1000)
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

# Report schemas
# Structured report taxonomy (REPORTING_CATEGORIES_SPEC.md). Replaces the
# legacy free-text `reason`. `details` is required only when category = other.
class ReportCategory(str, Enum):
    harassment = "harassment"
    inappropriate_photos = "inappropriate_photos"
    explicit_on_video_call = "explicit_on_video_call"
    underage = "underage"
    impersonation = "impersonation"
    scam_spam = "scam_spam"
    hate_speech = "hate_speech"
    violence_threat = "violence_threat"
    off_platform_solicitation = "off_platform_solicitation"
    other = "other"

class ReportContext(str, Enum):
    chat = "chat"
    video_call = "video_call"
    profile = "profile"

class ReportCreate(BaseModel):
    reported_firebase_uid: str
    category: ReportCategory
    context: ReportContext
    details: Optional[str] = Field(None, max_length=2000)

    @validator('details', always=True)
    def details_required_for_other(cls, v, values):
        # `other` is the long-tail catch-all; force a meaningful description so
        # admins can triage it. >=10 chars matches the iOS submit-gate.
        if values.get('category') == ReportCategory.other:
            if v is None or len(v.strip()) < 10:
                raise ValueError('details (min 10 chars) are required when category is "other"')
        return v

class ReportResponse(BaseModel):
    id: int
    reporter_id: int
    reported_user_id: int
    category: ReportCategory
    context: ReportContext
    details: Optional[str] = None
    status: str
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[int] = None

    class Config:
        from_attributes = True

class ReportStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(reviewed|dismissed)$")

class BanRequest(BaseModel):
    reason: Optional[str] = None

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
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None

    @validator('phone_number', always=True)
    def require_email_or_phone(cls, v, values):
        if not v and not values.get('email'):
            raise ValueError('Either email or phone_number must be provided')
        return v

class SwipeCreate(BaseModel):
    swiped_firebase_uid: str  # Changed from swiped_id: int to use Firebase UIDs
    liked: bool
    time_on_card_seconds: Optional[float] = None   # seconds the user viewed the card before swiping
    is_super_like: bool = False

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

class UserBase(BaseModel):
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = Field(None, max_length=32)
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

    @validator('phone_number', always=True)
    def require_email_or_phone(cls, v, values):
        if not v and not values.get('email'):
            raise ValueError('Either email or phone_number must be provided')
        return v

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
    user_id: Optional[int] = None  # Populated by endpoints; not on ORM model
    match_id: int
    user1_id: int
    user2_id: int
    # User names for display
    user1_name: Optional[str] = None
    user2_name: Optional[str] = None
    # Indicate which user is the "other" user from current user's perspective
    other_user_name: Optional[str] = None
    other_user_id: Optional[int] = None
    # Firebase UID of the other user — lets call-context surfaces (e.g. in-call
    # report/block) identify the user the same way every other surface does.
    other_user_firebase_uid: Optional[str] = None
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

# ============================================================================
# Scheduling V2 Schemas
# ============================================================================

class TextState(str, Enum):
    OPEN = "open"; LOCKED = "locked"; ARCHIVED = "archived"

class CallLifecycleStatus(str, Enum):   # distinct from the existing CallStatus enum
    NONE = "none"; PROPOSAL_PENDING = "proposal_pending"; SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"; PENDING_SURVEY = "pending_survey"
    COMPLETED = "completed"; NO_SHOW = "no_show"

class MatchLifecycle(str, Enum):
    ACTIVE = "active"; TERMINATED = "terminated"; EXPIRED = "expired"

class ProposeCallRequest(BaseModel):
    match_id: int
    proposed_start_utc: datetime

class CounterProposalRequest(BaseModel):
    proposed_start_utc: datetime

class VideoCallProposalResponse(BaseModel):
    id: int; match_id: int; proposer_user_id: int
    proposed_start_utc: datetime; proposed_end_utc: datetime
    status: str
    class Config: from_attributes = True

class ExitSurveyRequest(BaseModel):
    response: bool

class ExitSurveyResultResponse(BaseModel):
    match_lifecycle: str; call_status: str; text_state: str; contact_reveal_unlocked: bool

class ContactResponse(BaseModel):
    peer_phone_number: Optional[str] = None
    peer_phone_country_code: Optional[str] = None

class PeerUserSummary(BaseModel):
    id: int; name: Optional[str] = None; timezone: Optional[str] = None
    no_show_count: int = 0
    class Config: from_attributes = True

class MatchListItem(BaseModel):
    match_id: int
    peer_user: PeerUserSummary
    text_state: str; call_status: str; lifecycle: str
    text_locked_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    card_display: str
    active_proposal: Optional[VideoCallProposalResponse] = None
    scheduled_call: Optional[ScheduledCallResponse] = None
    exit_survey_self_response: Optional[bool] = None
    exit_survey_peer_response: Optional[bool] = None
    contact_reveal_unlocked: bool = False

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
