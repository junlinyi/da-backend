# app/services/matchmaking.py

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models import User
from app.services.age_service import birthdate_bounds_for_age_range
from typing import List, Tuple
from geopy.distance import geodesic
import math

def calculate_match_score(user1: User, user2: User) -> float:
    score = 0.0
    
    # Age compatibility (closer ages score higher). Age is derived from birthdate;
    # skip the age component if either user has no birthdate set yet.
    if user1.age is not None and user2.age is not None:
        age_diff = abs(user1.age - user2.age)
        age_score = max(0, 1 - (age_diff / 20))  # 20 years difference = 0 score
        score += age_score * 0.3  # 30% weight
    # Age score calculated
    
    # Location proximity
    if user1.latitude and user1.longitude and user2.latitude and user2.longitude:
        distance = geodesic(
            (user1.latitude, user1.longitude),
            (user2.latitude, user2.longitude)
        ).kilometers
        location_score = max(0, 1 - (distance / 100))  # 100km = 0 score
        score += location_score * 0.4  # 40% weight
        # Location score calculated
    else:
        # Location data missing
        pass
    
    # Common interests (if implemented)
    if hasattr(user1, 'interests') and hasattr(user2, 'interests'):
        common_interests = len(set(user1.interests) & set(user2.interests))
        interest_score = min(1, common_interests / 5)  # 5 common interests = max score
        score += interest_score * 0.3  # 30% weight
        # Interest score calculated
    
    return round(score, 2)

async def find_matches(
    user_id: int, 
    db: AsyncSession, 
    max_distance_km: float = None,
    min_match_score: float = 0.3
) -> List[Tuple[User, float]]:
    """
    Find potential matches for a user based on preferences and location.
    Returns a list of tuples containing (User, match_score).
    """
    # Get current user
    result = await db.execute(select(User).where(User.id == user_id))
    current_user = result.scalars().first()
    if not current_user:
        return []

    # Use user's max_distance_km if not provided
    if max_distance_km is None:
        max_distance_km = current_user.max_distance_km or 32

    # Age preference → birthdate range (age is derived from birthdate now).
    _bd_lower, _bd_upper = birthdate_bounds_for_age_range(
        current_user.min_age_preference, current_user.max_age_preference
    )

    # Get potential matches based on basic criteria - ENHANCED FILTERING
    base_query = select(User).where(
        User.id != user_id,  # Exclude current user
        User.gender.in_([current_user.preferred_gender, "any"]),  # Gender preference
        User.birthdate.between(_bd_lower, _bd_upper),  # Age window via birthdate
        # ADDITIONAL FILTERS: Ensure complete profiles only
        User.name.is_not(None),  # Must have a name
        User.birthdate.is_not(None),   # Must have a birthdate (→ age)
        User.gender.is_not(None), # Must have a gender
        User.latitude.is_not(None), # Must have location
        User.longitude.is_not(None)
    )
    
    # Fetch all potential matches
    result = await db.execute(base_query)
    potential_matches = result.scalars().all()
    
    # Found potential matches
    
    # Filter by distance and calculate match scores
    matches_with_scores = []
    for match in potential_matches:
        # Checking potential match
        
        # Skip if location data is missing (double-check)
        if not all([current_user.latitude, current_user.longitude, 
                   match.latitude, match.longitude]):
            # Skipping - missing location
            continue
            
        # Calculate distance
        user_location = (current_user.latitude, current_user.longitude)
        match_location = (match.latitude, match.longitude)
        distance = geodesic(user_location, match_location).kilometers
        
        # Skip if too far
        if distance > max_distance_km:
            # Skipping - too far
            continue
            
        # Calculate match score
        match_score = calculate_match_score(current_user, match)
        
        # Only include matches above minimum score
        if match_score >= min_match_score:
            # Valid match found
            matches_with_scores.append((match, match_score))
        else:
            # Skipping - score too low
            pass
    
    # Sort by match score (highest first)
    matches_with_scores.sort(key=lambda x: x[1], reverse=True)
    
    # Final matches calculated
    
    return matches_with_scores
