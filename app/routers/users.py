# app/routers/users.py

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import DATABASE_URL, get_db
from app.models import User
from app.schemas import UserResponse, UserUpdate, ProfileUpdate, PreferencesUpdate
from app.dependencies import verify_firebase_token
from pydantic import BaseModel
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

class UserCreateRequest(BaseModel):
    firebase_uid: str
    email: str
    name: str = None
    bio: str = None
    age: int = None
    gender: str = None
    interests: str = None  # Will be converted to array
    location: str = None
    latitude: float = None
    longitude: float = None
    state: str = None
    preferred_gender: str = None
    min_age_preference: int = None
    max_age_preference: int = None
    max_distance_km: int = None
    profile_image_url: str = None
    additional_image_urls: str = None  # Will be converted to array
    timezone: str = None
    
    def to_user_dict(self):
        """Convert to dict with proper array fields for User model"""
        data = self.dict(exclude_unset=True)
        
        # Convert interests string to array
        if data.get('interests'):
            data['interests'] = [interest.strip() for interest in data['interests'].split(',') if interest.strip()]
        
        # Convert additional_image_urls string to array
        if data.get('additional_image_urls'):
            data['additional_image_urls'] = [url.strip() for url in data['additional_image_urls'].split(',') if url.strip()]
        
        return data

@router.get("/me", response_model=UserResponse)
async def get_my_profile(decoded_token=Depends(verify_firebase_token), db: AsyncSession = Depends(get_db)):
    firebase_uid = decoded_token["uid"]
    email = decoded_token.get("email")

    result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    user = result.scalars().first()

    if not user:
        logger.info("No user found — creating...")
        user = User(firebase_uid=firebase_uid, email=email)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info(f"User created with ID: {user.id}")
    else:
        logger.info(f"User already exists with ID: {user.id}")

    return user

@router.get("/firebase/{firebase_uid}")
async def get_user_by_firebase_uid(firebase_uid: str, decoded_token=Depends(verify_firebase_token), db: AsyncSession = Depends(get_db)):
    """
    Get user by Firebase UID (for iOS app to fetch user details)
    """
    result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Return minimal user data for conversation display
    return {
        "name": user.name or "Unknown User",
        "profile_image_url": user.profile_image_url
    }

@router.put("/me/profile", response_model=UserResponse)
async def update_profile(
    profile: ProfileUpdate,
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Update user profile information during onboarding.
    """
    firebase_uid = decoded_token["uid"]
    result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update only the fields that are provided
    for key, value in profile.dict(exclude_unset=True).items():
        setattr(user, key, value)

    await db.commit()
    await db.refresh(user)
    logger.info(f"Updated profile for user {user.id}")
    return user

@router.put("/me/preferences", response_model=UserResponse)
async def update_preferences(
    preferences: PreferencesUpdate,
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Update user preferences during onboarding.
    """
    firebase_uid = decoded_token["uid"]
    result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update preferences
    for key, value in preferences.dict().items():
        setattr(user, key, value)

    await db.commit()
    await db.refresh(user)
    logger.info(f"Updated preferences for user {user.id}")
    return user

@router.get("/{user_id}", response_model=UserResponse)
async def get_profile(user_id: int, decoded_token=Depends(verify_firebase_token), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.put("/{user_id}", response_model=UserResponse)
async def update_user_by_id(user_id: int, profile: UserUpdate, decoded_token=Depends(verify_firebase_token), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Only allow users to update their own record
    if user.firebase_uid != decoded_token["uid"]:
        raise HTTPException(status_code=403, detail="Not authorized to update this user")

    for key, value in profile.dict(exclude_unset=True).items():
        setattr(user, key, value)

    await db.commit()
    return user

@router.delete("/{user_id}")
async def delete_account(user_id: int, decoded_token=Depends(verify_firebase_token), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Only allow users to delete their own account
    if user.firebase_uid != decoded_token["uid"]:
        raise HTTPException(status_code=403, detail="Not authorized to delete this user")

    await db.delete(user)
    await db.commit()
    return {"message": "User deleted successfully"}

@router.post("/create", response_model=UserResponse)
async def create_user(
    user: UserCreateRequest = Body(...),
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db)
):
    logger.info(f"[USER CREATE] Attempting to create/update user: {user.firebase_uid} {user.email}")
    # Only allow creating/updating own user record
    if user.firebase_uid != decoded_token["uid"]:
        raise HTTPException(status_code=403, detail="firebase_uid must match authenticated user")
    try:
        result = await db.execute(select(User).where(User.firebase_uid == user.firebase_uid))
        db_user = result.scalars().first()
        if db_user:
            logger.info(f"[USER CREATE] User already exists, updating: {db_user.id}")
            user_data = user.to_user_dict()
            for key, value in user_data.items():
                setattr(db_user, key, value)
        else:
            user_data = user.to_user_dict()
            db_user = User(**user_data)
            db.add(db_user)
            logger.info(f"[USER CREATE] New user will be created: {user.firebase_uid}")
        await db.commit()
        await db.refresh(db_user)
        logger.info(f"[USER CREATE] User created/updated successfully: {db_user.id}")
        return db_user
    except Exception as e:
        logger.error(f"[USER CREATE] Error creating/updating user: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create/update user: {e}")
