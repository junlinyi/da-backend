# app/schemas.py

from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
from datetime import datetime
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
    latitude: float
    longitude: float
    city: Optional[str] = None
    state: Optional[str] = None

# TimeSlot structure to match frontend
class TimeSlot(BaseModel):
    startTime: datetime
    endTime: datetime
    isAvailable: bool

# Comprehensive User schema that matches frontend
class UserResponse(BaseModel):
    id: int
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
    last_active: Optional[datetime] = None
    profile_completed: Optional[bool] = None
    is_verified: Optional[bool] = None
    strikes: Optional[int] = None

# Profile update schema - used by iOS app for /me/profile endpoint
class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None
    age: Optional[int] = Field(None, ge=18, le=100)
    gender: Optional[Gender] = None
    interests: Optional[List[str]] = None
    location: Optional[Location] = None
    profileImageURL: Optional[str] = None

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
class MessageCreate(BaseModel):
    content: str
    message_type: Optional[str] = "text"

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
