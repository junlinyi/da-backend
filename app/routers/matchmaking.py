from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.services.matchmaking import find_matches
from app.database import get_db
from app.models import User, Swipe
from app.schemas import SwipeCreate, UserResponse
from app.dependencies import verify_firebase_token
from app.services.match_creation import create_match_in_firestore
from typing import List
from datetime import datetime, timedelta

router = APIRouter()

@router.get("/potential-matches")
async def get_potential_matches(
    user_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get potential matches for a user (iOS app endpoint)
    """
    try:
        # Get user by Firebase UID
        result = await db.execute(select(User).where(User.firebase_uid == user_id))
        current_user = result.scalars().first()
        
        if not current_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get today's swipes
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        swipes_result = await db.execute(
            select(Swipe)
            .where(Swipe.swiper_id == current_user.id)
            .where(Swipe.created_at >= today)
        )
        today_swipes = swipes_result.scalars().all()
        swiped_ids = {swipe.swiped_id for swipe in today_swipes}

        # Get potential matches
        matches_with_scores = await find_matches(current_user.id, db)
        
        # Filter out already swiped users and format response
        potential_matches = []
        for match, score in matches_with_scores:
            if match.id not in swiped_ids:
                potential_matches.append({
                    "id": match.firebase_uid,
                    "name": match.name or "",
                    "age": match.age,
                    "bio": match.bio or "",
                    "gender": match.gender,
                    "interests": match.interests or [],
                    "profileImageUrl": match.profile_image_url,
                    "location": {
                        "latitude": match.latitude,
                        "longitude": match.longitude,
                        "city": match.city,
                        "state": match.state
                    } if match.latitude and match.longitude else None,
                    "matchScore": score
                })

        # Take top 7 matches
        top_matches = potential_matches[:7]
        remaining_swipes = max(0, 7 - len(today_swipes))

        return {
            "matches": top_matches,
            "remainingSwipes": remaining_swipes
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{user_id}/matches", response_model=List[UserResponse])
async def get_matches(user_id: int, db: AsyncSession = Depends(get_db)):
    matches = await find_matches(user_id, db)

    # TODO: should we raise an exception if no matches?
    if not matches:
        raise HTTPException(status_code=404, detail="No matches found")
    return matches


@router.post("/swipe")
async def swipe_user(
    swipe: SwipeCreate,
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db)
):
    swiper_firebase_uid = decoded_token["uid"]

    # Get swiper User object
    result = await db.execute(select(User).where(User.firebase_uid == swiper_firebase_uid))
    swiper = result.scalar_one_or_none()
    if not swiper:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent swiping on self
    if swiper.id == swipe.swiped_id:
        raise HTTPException(status_code=400, detail="Cannot swipe on yourself")

    # Save swipe
    swipe_obj = Swipe(swiper_id=swiper.id, swiped_id=swipe.swiped_id, liked=swipe.liked)
    db.add(swipe_obj)
    await db.commit()

    # If it's a like, check if the other user already liked them
    if swipe.liked:
        result = await db.execute(
            select(Swipe)
            .where(Swipe.swiper_id == swipe.swiped_id)
            .where(Swipe.swiped_id == swiper.id)
            .where(Swipe.liked == True)
        )
        reciprocal_swipe = result.scalar_one_or_none()

        if reciprocal_swipe:
            # Get the other user
            result = await db.execute(select(User).where(User.id == swipe.swiped_id))
            swiped_user = result.scalar_one_or_none()

            if swiped_user:
                # Create match in Firestore
                create_match_in_firestore(swiper.firebase_uid, swiped_user.firebase_uid)
                return {"message": "It's a match!"}

    return {"message": "Swipe recorded"}
