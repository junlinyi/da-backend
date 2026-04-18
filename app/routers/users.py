# app/routers/users.py

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_, and_
from app.database import DATABASE_URL, get_db
from app.models import User, Match, Conversation
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
        if key == 'location' and isinstance(value, dict):
            # Location is a nested object — map to flat DB columns
            user.location = value.get('city')
            if value.get('latitude') is not None:
                user.latitude = value['latitude']
            if value.get('longitude') is not None:
                user.longitude = value['longitude']
            if value.get('state') is not None:
                user.state = value['state']
        elif key == 'profileImageURL':
            user.profile_image_url = value
        else:
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

@router.post("/me/device-token")
async def register_device_token(
    payload: dict = Body(...),
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Register or update the APNs/FCM device token for the authenticated user.
    Called by the iOS app on every launch after notification permission is granted.

    Body: { "device_token": "<hex token string>" }
    """
    token = payload.get("device_token", "").strip()
    if not token:
        raise HTTPException(status_code=422, detail="device_token is required")

    firebase_uid = decoded_token["uid"]
    result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.device_token = token
    await db.commit()
    logger.info(f"[PUSH] Registered device token for user {user.id}")
    return {"status": "ok"}


@router.get("/{user_id}", response_model=UserResponse)
async def get_profile(user_id: int, decoded_token=Depends(verify_firebase_token), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.put("/{user_id}", response_model=UserResponse)
async def update_user_by_id(user_id: int, profile: UserUpdate, decoded_token=Depends(verify_firebase_token), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
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
    from datetime import datetime, timezone
    result = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Only allow users to delete their own account
    if user.firebase_uid != decoded_token["uid"]:
        raise HTTPException(status_code=403, detail="Not authorized to delete this user")

    # Soft delete: stamp deleted_at and scrub PII (GDPR)
    now = datetime.now(timezone.utc)
    user.deleted_at = now
    user.is_active = False
    user.email = f"deleted_{user.id}@deleted.invalid"
    user.name = "Deleted User"
    user.bio = None
    user.profile_image_url = None
    user.additional_image_urls = None
    user.location = None
    user.latitude = None
    user.longitude = None
    user.prompts = None
    await db.commit()
    return {"message": "User deleted successfully"}

@router.post("/me/block/{blocked_firebase_uid}")
async def block_user(
    blocked_firebase_uid: str,
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Block a user by their Firebase UID. This marks the match as blocked
    and deactivates the conversation between the two users.
    """
    current_firebase_uid = decoded_token["uid"]

    if current_firebase_uid == blocked_firebase_uid:
        raise HTTPException(status_code=400, detail="Cannot block yourself")

    # Resolve both users
    current_result = await db.execute(select(User).where(User.firebase_uid == current_firebase_uid))
    current_user = current_result.scalars().first()
    if not current_user:
        raise HTTPException(status_code=404, detail="Current user not found")

    blocked_result = await db.execute(select(User).where(User.firebase_uid == blocked_firebase_uid))
    blocked_user = blocked_result.scalars().first()
    if not blocked_user:
        raise HTTPException(status_code=404, detail="Blocked user not found")

    # Find the match (either direction)
    match_result = await db.execute(
        select(Match).where(
            or_(
                and_(Match.user_id == current_user.id, Match.matched_user_id == blocked_user.id),
                and_(Match.user_id == blocked_user.id, Match.matched_user_id == current_user.id)
            )
        )
    )
    match = match_result.scalars().first()

    if match:
        # Mark the blocker's side as blocked
        if match.user_id == current_user.id:
            match.user1_status = "blocked"
        else:
            match.user2_status = "blocked"
        match.status = "blocked"

    # Deactivate the conversation
    conv_result = await db.execute(
        select(Conversation).where(
            or_(
                and_(Conversation.user1_id == current_user.id, Conversation.user2_id == blocked_user.id),
                and_(Conversation.user1_id == blocked_user.id, Conversation.user2_id == current_user.id)
            )
        )
    )
    conversation = conv_result.scalars().first()
    if conversation:
        conversation.is_active = False

    await db.commit()
    logger.info(f"User {current_user.id} blocked user {blocked_user.id}")

    # Archive the Firestore conversation so iOS stops showing it (SAFE-03)
    try:
        from firebase_admin import firestore as fs_admin
        fs_db = fs_admin.client()
        # Conversation doc is keyed by sorted UIDs: "{uid_a}_{uid_b}"
        sorted_uids = "_".join(sorted([current_firebase_uid, blocked_firebase_uid]))
        conv_ref = fs_db.collection("conversations").document(sorted_uids)
        conv_ref.set({"archived": True, "active": False}, merge=True)
        logger.info(f"Archived Firestore conversation {sorted_uids}")
    except Exception as exc:
        # Non-fatal: Postgres block already applied; log and continue
        logger.warning(f"Failed to archive Firestore conversation on block: {exc}")

    return {"message": "User blocked successfully"}


@router.post("/me/unblock/{blocked_firebase_uid}")
async def unblock_user(
    blocked_firebase_uid: str,
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Unblock a user by their Firebase UID. Restores the match status to active
    and reactivates the conversation.
    """
    current_firebase_uid = decoded_token["uid"]

    if current_firebase_uid == blocked_firebase_uid:
        raise HTTPException(status_code=400, detail="Cannot unblock yourself")

    current_result = await db.execute(select(User).where(User.firebase_uid == current_firebase_uid))
    current_user = current_result.scalars().first()
    if not current_user:
        raise HTTPException(status_code=404, detail="Current user not found")

    blocked_result = await db.execute(select(User).where(User.firebase_uid == blocked_firebase_uid))
    blocked_user = blocked_result.scalars().first()
    if not blocked_user:
        raise HTTPException(status_code=404, detail="User not found")

    match_result = await db.execute(
        select(Match).where(
            or_(
                and_(Match.user_id == current_user.id, Match.matched_user_id == blocked_user.id),
                and_(Match.user_id == blocked_user.id, Match.matched_user_id == current_user.id)
            )
        )
    )
    match = match_result.scalars().first()

    if match:
        if match.user_id == current_user.id:
            match.user1_status = "active"
        else:
            match.user2_status = "active"
        # Only restore match status if neither side is blocked
        if match.user1_status == "active" and match.user2_status == "active":
            match.status = "accepted"

    conv_result = await db.execute(
        select(Conversation).where(
            or_(
                and_(Conversation.user1_id == current_user.id, Conversation.user2_id == blocked_user.id),
                and_(Conversation.user1_id == blocked_user.id, Conversation.user2_id == current_user.id)
            )
        )
    )
    conversation = conv_result.scalars().first()
    if conversation:
        conversation.is_active = True

    await db.commit()
    logger.info(f"User {current_user.id} unblocked user {blocked_user.id}")
    return {"message": "User unblocked successfully"}


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
