# app/schemas.py

from pydantic import BaseModel, EmailStr
from typing import Optional

class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    email: EmailStr
    bio: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    interests: Optional[str] = None
    location: Optional[str] = None

    class Config:
        from_attributes = True  # Enables ORM mode

class UserUpdate(BaseModel):
    bio: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    interests: Optional[str] = None
    location: Optional[str] = None

class SwipeCreate(BaseModel):
    swiped_id: int  # user being swiped on
    liked: bool
