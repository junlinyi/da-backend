# app/routers/users.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import DATABASE_URL, get_db
from app.models import User
from app.schemas import UserResponse, UserUpdate, ProfileUpdate, PreferencesUpdate
from app.dependencies import verify_firebase_token
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

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
async def get_profile(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.put("/{user_id}", response_model=UserResponse)
async def update_profile(user_id: int, profile: UserUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    for key, value in profile.dict(exclude_unset=True).items():
        setattr(user, key, value)

    await db.commit()
    return user

@router.delete("/{user_id}")
async def delete_account(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(user)
    await db.commit()
    return {"message": "User deleted successfully"}
