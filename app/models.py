# app/models.py

from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Boolean, Text, func
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    is_active = Column(Boolean, default=True)
    firebase_uid = Column(String, unique=True, nullable=False)
    
    # Profile Fields
    bio = Column(Text, nullable=True)
    age = Column(Integer, nullable=True)
    gender = Column(String, nullable=True)
    interests = Column(String, nullable=True)  # Comma-separated string of interests
    location = Column(String, nullable=True)  # City or coordinates
    preferred_gender = Column(String, nullable=True)  # e.g., "male", "female", "any"
    min_age_preference = Column(Integer, default=18)
    max_age_preference = Column(Integer, default=100)


class Match(Base):
    __tablename__ = "matches"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    matched_user_id = Column(Integer, ForeignKey("users.id"))
    timestamp = Column(DateTime, default=datetime.now())


class Swipe(Base):
    __tablename__ = "swipes"

    id = Column(Integer, primary_key=True, index=True)
    swiper_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    swiped_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    liked = Column(Boolean, default=False)  # True = like, False = pass
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
