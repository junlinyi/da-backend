# app/models.py

from datetime import datetime, time, date
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Boolean, Text, Float, func, ARRAY, UniqueConstraint, Time, Date, CheckConstraint
from sqlalchemy.orm import relationship
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    is_active = Column(Boolean, default=True)
    firebase_uid = Column(String, unique=True, nullable=False)
    
    # Profile Fields
    name = Column(String, nullable=True)
    bio = Column(Text, nullable=True)
    age = Column(Integer, nullable=True)
    gender = Column(String, nullable=True)
    interests = Column(ARRAY(String), nullable=True)  # Array of interests
    location = Column(String, nullable=True)  # City name
    latitude = Column(Float, nullable=True)  # Location coordinates
    longitude = Column(Float, nullable=True)
    state = Column(String, nullable=True)  # State field to match frontend Location struct
    preferred_gender = Column(String, nullable=True)  # e.g., "male", "female", "any"
    min_age_preference = Column(Integer, default=18)
    max_age_preference = Column(Integer, default=120)
    max_distance_km = Column(Integer, default=32)  # Maximum distance for matches (default 20 miles)
    
    # Profile Status
    last_active = Column(DateTime(timezone=True), server_default=func.now())
    profile_completed = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)
    strikes = Column(Integer, default=0)  # Add strikes field to match frontend
    
    # Profile Images
    profile_image_url = Column(String, nullable=True)
    additional_image_urls = Column(ARRAY(String), nullable=True)
    
    # Timezone
    timezone = Column(String, default='UTC')
    
    # Relationships
    weekly_availability = relationship("UserWeeklyAvailability", back_populates="user", cascade="all, delete-orphan")
    availability_overrides = relationship("UserAvailabilityOverride", back_populates="user", cascade="all, delete-orphan")
    timezone_info = relationship("UserTimezone", back_populates="user", uselist=False, cascade="all, delete-orphan")
    scheduling_preferences = relationship("UserSchedulingPreferences", back_populates="user", uselist=False, cascade="all, delete-orphan")
    
    # Call relationships
    scheduled_calls_as_user1 = relationship("ScheduledCall", foreign_keys="ScheduledCall.user1_id", back_populates="user1")
    scheduled_calls_as_user2 = relationship("ScheduledCall", foreign_keys="ScheduledCall.user2_id", back_populates="user2")
    call_ratings_given = relationship("CallRating", foreign_keys="CallRating.rater_id", back_populates="rater")
    call_ratings_received = relationship("CallRating", foreign_keys="CallRating.rated_user_id", back_populates="rated_user")
    
    # When2Meet style availability relationships
    default_availability = relationship("UserDefaultAvailability", back_populates="user", cascade="all, delete-orphan")
    override_availability = relationship("UserOverrideAvailability", back_populates="user", cascade="all, delete-orphan")


class Match(Base):
    __tablename__ = "matches"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    matched_user_id = Column(Integer, ForeignKey("users.id"))
    match_score = Column(Float, nullable=True)  # Score from 0 to 1
    status = Column(String, default="pending")  # pending, accepted, rejected
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Match metadata
    user1_last_active = Column(DateTime(timezone=True), server_default=func.now())
    user2_last_active = Column(DateTime(timezone=True), server_default=func.now())
    user1_unread_count = Column(Integer, default=0)
    user2_unread_count = Column(Integer, default=0)
    user1_status = Column(String, default="active")  # active, inactive, blocked
    user2_status = Column(String, default="active")
    
    # Relationships
    scheduled_calls = relationship("ScheduledCall", back_populates="match", cascade="all, delete-orphan")
    
    # Unique constraint to prevent duplicate matches
    __table_args__ = (
        UniqueConstraint('user_id', 'matched_user_id', name='uq_user_matched_user'),
    )


class Swipe(Base):
    __tablename__ = "swipes"

    id = Column(Integer, primary_key=True, index=True)
    swiper_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    swiped_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    liked = Column(Boolean, default=False)  # True = like, False = pass
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    match_score = Column(Float, nullable=True)  # Score from 0 to 1


class Conversation(Base):
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    user1_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user2_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_message = Column(Text, nullable=True)
    last_message_at = Column(DateTime(timezone=True), server_default=func.now())
    user1_unread_count = Column(Integer, default=0)
    user2_unread_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)


class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    message_type = Column(String, default="text")  # text, image, video, audio
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    is_read = Column(Boolean, default=False)
    firebase_id = Column(String, unique=True, nullable=True)  # Firebase message ID for syncing


# Video Call Scheduling Models

class UserWeeklyAvailability(Base):
    __tablename__ = "user_weekly_availability"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0=Sunday, 6=Saturday
    start_time = Column(Time, nullable=False)  # Local time in user's timezone
    end_time = Column(Time, nullable=False)  # Local time in user's timezone
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="weekly_availability")
    
    __table_args__ = (
        UniqueConstraint('user_id', 'day_of_week', 'start_time', 'end_time', name='uq_user_day_time_slot'),
    )


class UserAvailabilityOverride(Base):
    __tablename__ = "user_availability_overrides"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)  # Specific date
    start_time = Column(Time, nullable=False)  # Local time in user's timezone
    end_time = Column(Time, nullable=False)  # Local time in user's timezone
    reason = Column(String(255), nullable=True)  # Optional reason for override
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="availability_overrides")
    
    __table_args__ = (
        UniqueConstraint('user_id', 'date', 'start_time', 'end_time', name='uq_user_date_time_slot'),
    )


class UserTimezone(Base):
    __tablename__ = "user_timezones"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    timezone = Column(String(50), nullable=False, default='UTC')  # e.g., 'America/New_York'
    timezone_offset = Column(Integer, nullable=False, default=0)  # Offset in minutes from UTC
    dst_enabled = Column(Boolean, nullable=False, default=False)  # Daylight saving time enabled
    last_updated = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="timezone_info")


class ScheduledCall(Base):
    __tablename__ = "scheduled_calls"
    
    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    user1_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user2_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Call timing (stored in UTC for consistency)
    scheduled_start_utc = Column(DateTime(timezone=True), nullable=False)
    scheduled_end_utc = Column(DateTime(timezone=True), nullable=False)
    duration_minutes = Column(Integer, nullable=False, default=15)
    
    # Call status
    status = Column(String(20), nullable=False, default='scheduled')  # 'scheduled', 'in_progress', 'completed', 'cancelled', 'no_show'
    
    # User confirmations
    user1_confirmed = Column(Boolean, default=False)
    user2_confirmed = Column(Boolean, default=False)
    user1_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    user2_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Call metadata
    call_room_id = Column(String(255), nullable=True)  # Twilio room ID or similar
    call_started_at = Column(DateTime(timezone=True), nullable=True)
    call_ended_at = Column(DateTime(timezone=True), nullable=True)
    actual_duration_minutes = Column(Integer, nullable=True)
    
    # Rescheduling info
    original_call_id = Column(Integer, ForeignKey("scheduled_calls.id"), nullable=True)  # For tracking reschedules
    reschedule_count = Column(Integer, default=0)
    
    # Notifications
    user1_notified = Column(Boolean, default=False)
    user2_notified = Column(Boolean, default=False)
    reminder_sent = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    match = relationship("Match", back_populates="scheduled_calls")
    user1 = relationship("User", foreign_keys=[user1_id], back_populates="scheduled_calls_as_user1")
    user2 = relationship("User", foreign_keys=[user2_id], back_populates="scheduled_calls_as_user2")
    original_call = relationship("ScheduledCall", remote_side=[id], backref="rescheduled_calls")
    ratings = relationship("CallRating", back_populates="call", cascade="all, delete-orphan")


class CallRating(Base):
    __tablename__ = "call_ratings"
    
    id = Column(Integer, primary_key=True, index=True)
    call_id = Column(Integer, ForeignKey("scheduled_calls.id"), nullable=False)
    rater_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    rated_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    rating = Column(Integer, nullable=False)  # 1-5
    feedback = Column(Text, nullable=True)
    categories = Column(ARRAY(String), nullable=True)  # Array of negative categories if applicable
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    call = relationship("ScheduledCall", back_populates="ratings")
    rater = relationship("User", foreign_keys=[rater_id], back_populates="call_ratings_given")
    rated_user = relationship("User", foreign_keys=[rated_user_id], back_populates="call_ratings_received")
    
    __table_args__ = (
        UniqueConstraint('call_id', 'rater_id', name='uq_call_rater'),
    )


class UserSchedulingPreferences(Base):
    __tablename__ = "user_scheduling_preferences"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    
    # Scheduling preferences (fixed 15-minute calls)
    max_calls_per_week = Column(Integer, default=5)
    min_notice_hours = Column(Integer, default=2)  # Minimum notice required
    max_advance_days = Column(Integer, default=7)  # How far in advance to schedule
    
    # Time preferences (in user's local timezone)
    preferred_start_time = Column(Time, default=time(18, 0))  # 6 PM
    preferred_end_time = Column(Time, default=time(22, 0))  # 10 PM
    
    # Notification preferences
    email_notifications = Column(Boolean, default=True)
    push_notifications = Column(Boolean, default=True)
    reminder_hours_before = Column(Integer, default=1)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="scheduling_preferences")


class UserMatchCallPreferences(Base):
    __tablename__ = "user_match_call_preferences"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    matched_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Call preference status
    status = Column(String(20), nullable=False, default='pending')  # 'pending', 'wants_to_call', 'doesnt_want_to_call', 'already_called'
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Metadata
    last_common_availability_check = Column(DateTime(timezone=True), server_default=func.now())
    last_notification_sent = Column(DateTime(timezone=True), nullable=True)
    
    # Unique constraint to prevent duplicate preferences
    __table_args__ = (
        UniqueConstraint('user_id', 'matched_user_id', name='uq_user_match_call_preference'),
    )


# ============================================================================
# When2Meet Style Availability Models
# ============================================================================

class UserDefaultAvailability(Base):
    """User's default weekly availability in 30-minute slots (When2Meet style)"""
    __tablename__ = "user_default_availability"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0-6 (Sunday-Saturday)
    hour = Column(Integer, nullable=False)  # 0-23
    minute = Column(Integer, nullable=False)  # 0 or 30 (30-minute slots)
    is_available = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="default_availability")
    
    # Constraints
    __table_args__ = (
        CheckConstraint('day_of_week >= 0 AND day_of_week <= 6', name='valid_day_of_week'),
        CheckConstraint('hour >= 0 AND hour <= 23', name='valid_hour'),
        CheckConstraint('minute IN (0, 30)', name='valid_minute'),
        UniqueConstraint('user_id', 'day_of_week', 'hour', 'minute', name='unique_user_time_slot'),
    )


class UserOverrideAvailability(Base):
    """User's override availability for specific weeks (When2Meet style)"""
    __tablename__ = "user_override_availability"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    week_start_date = Column(Date, nullable=False)  # YYYY-MM-DD format
    day_of_week = Column(Integer, nullable=False)  # 0-6 (Sunday-Saturday)
    hour = Column(Integer, nullable=False)  # 0-23
    minute = Column(Integer, nullable=False)  # 0 or 30 (30-minute slots)
    is_available = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="override_availability")
    
    # Constraints
    __table_args__ = (
        CheckConstraint('day_of_week >= 0 AND day_of_week <= 6', name='valid_day_of_week'),
        CheckConstraint('hour >= 0 AND hour <= 23', name='valid_hour'),
        CheckConstraint('minute IN (0, 30)', name='valid_minute'),
        UniqueConstraint('user_id', 'week_start_date', 'day_of_week', 'hour', 'minute', name='unique_user_week_time_slot'),
    )
