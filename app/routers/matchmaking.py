from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from services.matchmaking import find_matches
from database import get_db
from models import User, Swipe
from schemas import SwipeCreate, UserResponse
from dependencies import verify_firebase_token
from services.match_creation import create_match_in_firestore

router = APIRouter()

@router.get("/{user_id}/matches", response_model=list[UserResponse])
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
