# app/models.py

from datetime import datetime, time, date
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Boolean, Text, Float, func, ARRAY, UniqueConstraint, Time, Date, CheckConstraint, JSON, Index
from sqlalchemy.orm import relationship
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=True)
    phone_number = Column(String, unique=True, index=True, nullable=True)
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
    is_admin = Column(Boolean, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # GDPR soft delete
    
    # Profile Images
    profile_image_url = Column(String, nullable=True)
    additional_image_urls = Column(ARRAY(String), nullable=True)

    # Profile Prompts — stored as [{question: str, answer: str}, ...]
    prompts = Column(JSON, nullable=True)
    
    # Timezone
    timezone = Column(String, default='UTC')

    # Premium
    is_premium = Column(Boolean, nullable=False, default=False)
    premium_expires_at = Column(DateTime(timezone=True), nullable=True)
    last_weekly_boost_granted = Column(Date, nullable=True)

    # Accountability tracking
    no_show_count = Column(Integer, default=0, nullable=False)
    last_no_show_at = Column(DateTime(timezone=True), nullable=True)

    # Push Notifications
    device_token = Column(String, nullable=True)  # APNs/FCM device token
    
    # Relationships
    reports_filed = relationship("Report", foreign_keys="Report.reporter_id", back_populates="reporter", cascade="all, delete-orphan")
    reports_received = relationship("Report", foreign_keys="Report.reported_user_id", back_populates="reported_user", cascade="all, delete-orphan")
    scheduling_preferences = relationship("UserSchedulingPreferences", back_populates="user", uselist=False, cascade="all, delete-orphan")

    # Call relationships
    scheduled_calls_as_user1 = relationship("ScheduledCall", foreign_keys="ScheduledCall.user1_id", back_populates="user1")
    scheduled_calls_as_user2 = relationship("ScheduledCall", foreign_keys="ScheduledCall.user2_id", back_populates="user2")
    call_ratings_given = relationship("CallRating", foreign_keys="CallRating.rater_id", back_populates="rater")
    call_ratings_received = relationship("CallRating", foreign_keys="CallRating.rated_user_id", back_populates="rated_user")

    # ML matchmaking relationships
    values_profile = relationship("UserValues", back_populates="user", uselist=False, cascade="all, delete-orphan")
    feature_vector = relationship("UserFeatureVector", back_populates="user", uselist=False, cascade="all, delete-orphan")


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    matched_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    match_score = Column(Float, nullable=True)  # Score from 0 to 1
    status = Column(String, default="pending")  # pending, accepted, rejected
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # GDPR soft delete
    
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
    swiper_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    swiped_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    liked = Column(Boolean, default=False)  # True = like, False = pass
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    match_score = Column(Float, nullable=True)  # Score from 0 to 1


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user1_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user2_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_message = Column(Text, nullable=True)
    last_message_at = Column(DateTime(timezone=True), server_default=func.now())
    user1_unread_count = Column(Integer, default=0)
    user2_unread_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # GDPR soft delete


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    message_type = Column(String, default="text")  # text, image, video, audio
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    is_read = Column(Boolean, default=False)
    firebase_id = Column(String, unique=True, nullable=True)  # Firebase message ID for syncing


# Video Call Scheduling Models

class ScheduledCall(Base):
    __tablename__ = "scheduled_calls"
    
    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id", ondelete="CASCADE"), nullable=False)
    user1_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user2_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

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

    # Cancellation accountability
    cancelled_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    cancellation_reason = Column(String(50), nullable=True)  # 'user', 'no_show', 'system', 'unmatch'
    
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
    cancelled_by = relationship("User", foreign_keys=[cancelled_by_id])
    original_call = relationship("ScheduledCall", remote_side=[id], backref="rescheduled_calls")
    ratings = relationship("CallRating", back_populates="call", cascade="all, delete-orphan")
    video_room = relationship("VideoCallRoom", back_populates="scheduled_call", uselist=False)


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


# ============================================================================
# Scheduling Proposal System Models
# ============================================================================

class SchedulingProposal(Base):
    """Scheduling proposals from one user to another with multiple time slot options"""
    __tablename__ = "scheduling_proposals"
    
    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id", ondelete="CASCADE"), nullable=False)
    proposer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    receiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Proposal status: pending, accepted, rejected, counter_proposed, expired
    status = Column(String(20), nullable=False, default="pending")
    message = Column(Text, nullable=True)  # Optional message from proposer
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)  # Auto-expire after 24 hours
    responded_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    match = relationship("Match", backref="scheduling_proposals")
    proposer = relationship("User", foreign_keys=[proposer_id])
    receiver = relationship("User", foreign_keys=[receiver_id])
    time_slots = relationship("ProposalTimeSlot", back_populates="proposal", cascade="all, delete-orphan")
    responses = relationship("ProposalResponse", back_populates="proposal", cascade="all, delete-orphan")


class ProposalTimeSlot(Base):
    """Time slots proposed within a scheduling proposal (2-3 options)"""
    __tablename__ = "proposal_time_slots"
    
    id = Column(Integer, primary_key=True, index=True)
    proposal_id = Column(Integer, ForeignKey("scheduling_proposals.id", ondelete="CASCADE"), nullable=False)
    
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    is_selected = Column(Boolean, nullable=False, default=False)  # Set to True when accepted
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    proposal = relationship("SchedulingProposal", back_populates="time_slots")


class ProposalResponse(Base):
    """Response to a scheduling proposal (accept/reject/counter)"""
    __tablename__ = "proposal_responses"
    
    id = Column(Integer, primary_key=True, index=True)
    proposal_id = Column(Integer, ForeignKey("scheduling_proposals.id", ondelete="CASCADE"), nullable=False)
    
    # Response type: accept, reject, counter_propose
    response_type = Column(String(20), nullable=False)
    selected_slot_id = Column(Integer, ForeignKey("proposal_time_slots.id"), nullable=True)  # For accepts
    counter_proposal_message = Column(Text, nullable=True)  # For counter proposals
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    proposal = relationship("SchedulingProposal", back_populates="responses")
    selected_slot = relationship("ProposalTimeSlot")
    counter_time_slots = relationship("CounterProposalTimeSlot", back_populates="response", cascade="all, delete-orphan")


class CounterProposalTimeSlot(Base):
    """Time slots for counter proposals"""
    __tablename__ = "counter_proposal_time_slots"
    
    id = Column(Integer, primary_key=True, index=True)
    response_id = Column(Integer, ForeignKey("proposal_responses.id", ondelete="CASCADE"), nullable=False)
    
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    response = relationship("ProposalResponse", back_populates="counter_time_slots")


# ============================================================================
# Video Call Room Models
# ============================================================================

class Report(Base):
    """User reports filed against other users"""
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reported_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    reason = Column(String(100), nullable=False)
    details = Column(Text, nullable=True)

    # "pending" | "reviewed" | "dismissed"
    status = Column(String(20), nullable=False, default="pending")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relationships
    reporter = relationship("User", foreign_keys=[reporter_id], back_populates="reports_filed")
    reported_user = relationship("User", foreign_keys=[reported_user_id], back_populates="reports_received")
    reviewer = relationship("User", foreign_keys=[reviewed_by])

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'reviewed', 'dismissed')", name='valid_report_status'),
    )


class CallRequest(Base):
    """Tier 1 post-match spontaneous call requests (5-minute live call window)"""
    __tablename__ = "call_requests"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False)   # User B (triggered the match)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False)   # User A (was swiped on)
    status = Column(String(20), nullable=False, default="pending")           # pending, accepted, declined, expired
    room_name = Column(String(255), nullable=True)                           # set on accept: "tier1-{id}"
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)             # created_at + 5 minutes

    requester = relationship("User", foreign_keys=[requester_id])
    recipient = relationship("User", foreign_keys=[recipient_id])
    match = relationship("Match")

    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','declined','expired')", name="valid_call_request_status"),
    )


# ============================================================================
# ML Matchmaking Infrastructure Models
# ============================================================================

class UserValues(Base):
    """Structured values & personality questionnaire — one row per user."""
    __tablename__ = "user_values"

    id      = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    # Relationship intent
    relationship_goal = Column(String(30), nullable=False, default="long_term")

    # Family plans
    wants_children         = Column(String(20), nullable=False, default="open")
    children_timeline_years = Column(Integer, nullable=True)

    # Lifestyle (1-5 Likert)
    activity_level    = Column(Integer, nullable=True)
    social_energy     = Column(Integer, nullable=True)
    night_owl_score   = Column(Integer, nullable=True)
    travel_importance = Column(Integer, nullable=True)

    # Values (1-5 Likert)
    religious_importance  = Column(Integer, nullable=True)
    religion              = Column(String(50), nullable=True)
    political_leaning     = Column(Integer, nullable=True)
    financial_priority    = Column(Integer, nullable=True)
    career_ambition       = Column(Integer, nullable=True)
    environmental_concern = Column(Integer, nullable=True)

    # Big Five personality (1.0-5.0)
    big5_openness          = Column(Float, nullable=True)
    big5_conscientiousness = Column(Float, nullable=True)
    big5_extraversion      = Column(Float, nullable=True)
    big5_agreeableness     = Column(Float, nullable=True)
    big5_neuroticism       = Column(Float, nullable=True)

    # Communication
    communication_directness = Column(Integer, nullable=True)
    conflict_style           = Column(String(30), nullable=True, default="discuss")

    # Deal-breakers
    dealbreaker_smoking       = Column(Boolean, default=False)
    dealbreaker_drugs         = Column(Boolean, default=False)
    dealbreaker_drinking      = Column(Boolean, default=False)
    dealbreaker_diff_religion = Column(Boolean, default=False)
    dealbreaker_diff_politics = Column(Boolean, default=False)
    dealbreaker_no_children   = Column(Boolean, default=False)

    completed_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="values_profile")


class UserFeatureVector(Base):
    """
    Computed feature store — one JSONB blob per user, refreshed by the
    feature service.  Acts as the 'online store' for real-time ranking.
    """
    __tablename__ = "user_feature_vectors"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    features    = Column(JSON, nullable=False, default=dict)
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    version     = Column(Integer, nullable=False, default=1)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="feature_vector")


class BehavioralEvent(Base):
    """
    Append-only event log — every meaningful user action.
    Used to compute behavioral features and to train future ML models.
    """
    __tablename__ = "behavioral_events"

    id             = Column(Integer, primary_key=True, index=True)
    user_id        = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    target_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # e.g. swipe_like | swipe_pass | message_sent | call_completed | call_rated
    event_type  = Column(String(50), nullable=False)
    event_value = Column(Float, nullable=True)   # e.g. message length, rating
    event_meta  = Column(JSON, default=dict)

    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user        = relationship("User", foreign_keys=[user_id])
    target_user = relationship("User", foreign_keys=[target_user_id])


class MatchOutcome(Base):
    """
    Outcome tracking per match — the ground-truth labels for ML training.
    Continuously updated as the match moves through the funnel.
    """
    __tablename__ = "match_outcomes"

    id       = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id", ondelete="CASCADE"), unique=True, nullable=False)
    user1_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user2_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Funnel timestamps
    matched_at         = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    first_message_at   = Column(DateTime(timezone=True), nullable=True)
    reciprocal_msg_at  = Column(DateTime(timezone=True), nullable=True)
    call_scheduled_at  = Column(DateTime(timezone=True), nullable=True)
    call_completed_at  = Column(DateTime(timezone=True), nullable=True)
    second_call_at     = Column(DateTime(timezone=True), nullable=True)

    # Quality signals
    user1_call_rating = Column(Integer, nullable=True)
    user2_call_rating = Column(Integer, nullable=True)
    avg_call_rating   = Column(Float, nullable=True)

    # Long-term follow-up
    still_talking_30d   = Column(Boolean, nullable=True)
    relationship_formed = Column(Boolean, nullable=True)
    survey_responded_at = Column(DateTime(timezone=True), nullable=True)

    # ML training label (0–1)
    compatibility_label = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    match = relationship("Match", backref="outcome")
    user1 = relationship("User", foreign_keys=[user1_id])
    user2 = relationship("User", foreign_keys=[user2_id])


class PremiumUnlock(Base):
    """Tracks daily profile unlocks by premium users from the Likes tab."""
    __tablename__ = "premium_unlocks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    unlocked_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    unlocked_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # NULL = unlocked but not yet acted on; 'like' | 'pass' once responded
    action = Column(String(10), nullable=True)
    match_id = Column(Integer, ForeignKey("matches.id", ondelete="SET NULL"), nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    unlocked_user = relationship("User", foreign_keys=[unlocked_user_id])
    match = relationship("Match", foreign_keys=[match_id])

    __table_args__ = (
        UniqueConstraint("user_id", "unlocked_user_id", name="uq_premium_unlock"),
    )


class ProfileBoost(Base):
    """Tracks active profile boosts (premium weekly grant or à la carte purchase)."""
    __tablename__ = "profile_boosts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    # 'premium_weekly' | 'alacarte'
    source = Column(String(20), nullable=False)
    # StoreKit transaction ID for à la carte; NULL for premium_weekly
    purchase_token = Column(String(255), nullable=True)

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        CheckConstraint("expires_at > started_at", name="boost_expires_after_start"),
        Index("idx_boosts_user_active", "user_id", "expires_at"),
    )


class VideoCallRoom(Base):
    """Video call rooms for scheduled calls using Twilio"""
    __tablename__ = "video_call_rooms"
    
    id = Column(Integer, primary_key=True, index=True)
    scheduled_call_id = Column(Integer, ForeignKey("scheduled_calls.id"), nullable=False)
    room_name = Column(String(255), unique=True, nullable=False, index=True)
    room_sid = Column(String(255), nullable=True)  # Twilio room SID
    status = Column(String(50), nullable=False, server_default='active')  # 'active', 'ended', 'expired'
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    scheduled_call = relationship("ScheduledCall", back_populates="video_room")
    
    __table_args__ = (
        CheckConstraint("status IN ('active', 'ended', 'expired')", name='valid_status'),
    )
