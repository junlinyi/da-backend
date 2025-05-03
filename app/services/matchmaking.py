# app/services/matchmaking.py

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import User
from typing import List

async def find_matches(user_id: int, db: AsyncSession) -> List[User]:
    # Get current user
    result = await db.execute(select(User).where(User.id == user_id))
    current_user = result.scalars().first()
    if not current_user:
        return []

    # Get potential matches
    query = select(User).where(
        User.id != user_id,  # Exclude current user
        # TODO: accomodate gender preferences
        User.gender.in_([current_user.preferred_gender]),  # or include "any"
        # TODO: make age range customizable
        User.age.between(current_user.min_age_preference, current_user.max_age_preference),
        # TODO: make customizable / premium feature for travel mode
        User.location == current_user.location  # Same location
    )
    result = await db.execute(query)
    return result.scalars().all()
