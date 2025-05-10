# app/schemas.py

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List

class UserCreate(BaseModel):
    email: EmailStr

class UserResponse(BaseModel):
    id: int
    email: EmailStr
    bio: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    interests: Optional[str] = None
    location: Optional[str] = None
    preferred_gender: Optional[str] = None
    min_age_preference: Optional[int] = 18
    max_age_preference: Optional[int] = 100

    class Config:
        from_attributes = True  # Enables ORM mode

class ProfileUpdate(BaseModel):
    bio: Optional[str] = None
    age: Optional[int] = Field(None, ge=18, le=100)
    gender: Optional[str] = Field(None, pattern="^(male|female|other)$")
    interests: Optional[str] = None
    location: Optional[str] = None

class PreferencesUpdate(BaseModel):
    preferred_gender: str = Field(..., pattern="^(male|female|any)$")
    min_age_preference: int = Field(..., ge=18, le=100)
    max_age_preference: int = Field(..., ge=18, le=100)

class UserUpdate(BaseModel):
    bio: Optional[str] = None
    age: Optional[int] = Field(None, ge=18, le=100)
    gender: Optional[str] = Field(None, pattern="^(male|female|other)$")
    interests: Optional[str] = None
    location: Optional[str] = None
    preferred_gender: Optional[str] = Field(None, pattern="^(male|female|any)$")
    min_age_preference: Optional[int] = Field(None, ge=18, le=100)
    max_age_preference: Optional[int] = Field(None, ge=18, le=100)

class SwipeCreate(BaseModel):
    swiped_id: int  # user being swiped on
    liked: bool
