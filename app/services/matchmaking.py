# app/services/matchmaking.py

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models import User
from typing import List, Tuple
from geopy.distance import geodesic
import math

def calculate_match_score(user1: User, user2: User) -> float:
    score = 0.0
    
    # Age compatibility (closer ages score higher)
    age_diff = abs(user1.age - user2.age)
    age_score = max(0, 1 - (age_diff / 20))  # 20 years difference = 0 score
    score += age_score * 0.3  # 30% weight
    print(f"Age Score: {age_score}, Age Difference: {age_diff}")
    
    # Location proximity
    if user1.latitude and user1.longitude and user2.latitude and user2.longitude:
        distance = geodesic(
            (user1.latitude, user1.longitude),
            (user2.latitude, user2.longitude)
        ).kilometers
        location_score = max(0, 1 - (distance / 100))  # 100km = 0 score
        score += location_score * 0.4  # 40% weight
        print(f"Location Score: {location_score}, Distance: {distance} km")
    else:
        print("Location data missing for one or both users.")
    
    # Common interests (if implemented)
    if hasattr(user1, 'interests') and hasattr(user2, 'interests'):
        common_interests = len(set(user1.interests) & set(user2.interests))
        interest_score = min(1, common_interests / 5)  # 5 common interests = max score
        score += interest_score * 0.3  # 30% weight
        print(f"Interest Score: {interest_score}, Common Interests: {common_interests}")
    
    return round(score, 2)

async def find_matches(
    user_id: int, 
    db: AsyncSession, 
    max_distance_km: float = 50,
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

    # Get potential matches based on basic criteria
    base_query = select(User).where(
        User.id != user_id,  # Exclude current user
        User.gender.in_([current_user.preferred_gender, "any"]),  # Gender preference
        User.age.between(current_user.min_age_preference, current_user.max_age_preference)
    )
    
    # Fetch all potential matches
    result = await db.execute(base_query)
    potential_matches = result.scalars().all()
    
    # Filter by distance and calculate match scores
    matches_with_scores = []
    for match in potential_matches:
        # Skip if location data is missing
        if not all([current_user.latitude, current_user.longitude, 
                   match.latitude, match.longitude]):
            continue
            
        # Calculate distance
        user_location = (current_user.latitude, current_user.longitude)
        match_location = (match.latitude, match.longitude)
        distance = geodesic(user_location, match_location).kilometers
        
        # Skip if too far
        if distance > max_distance_km:
            continue
            
        # Calculate match score
        match_score = calculate_match_score(current_user, match)
        
        # Only include matches above minimum score
        if match_score >= min_match_score:
            matches_with_scores.append((match, match_score))
    
    # Sort by match score (highest first)
    matches_with_scores.sort(key=lambda x: x[1], reverse=True)
    
    return matches_with_scores
