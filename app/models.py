# app/models.py

from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Boolean, Text, Float, func, ARRAY, UniqueConstraint
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
    
    # TODO: Add available_schedule field for TimeSlot support
    # available_schedule = Column(JSON, nullable=True)  # Store as JSON array


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
