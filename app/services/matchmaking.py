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

    # Get potential matches based on basic criteria - ENHANCED FILTERING
    base_query = select(User).where(
        User.id != user_id,  # Exclude current user
        User.gender.in_([current_user.preferred_gender, "any"]),  # Gender preference
        User.age.between(current_user.min_age_preference, current_user.max_age_preference),
        # ADDITIONAL FILTERS: Ensure complete profiles only
        User.name.is_not(None),  # Must have a name
        User.age.is_not(None),   # Must have an age
        User.gender.is_not(None), # Must have a gender
        User.latitude.is_not(None), # Must have location
        User.longitude.is_not(None)
    )
    
    # Fetch all potential matches
    result = await db.execute(base_query)
    potential_matches = result.scalars().all()
    
    print(f"🔍 Found {len(potential_matches)} potential matches for user {current_user.name} (ID: {user_id})")
    
    # Filter by distance and calculate match scores
    matches_with_scores = []
    for match in potential_matches:
        print(f"  📋 Checking match: {match.name} (ID: {match.id}, Age: {match.age}, Gender: {match.gender})")
        
        # Skip if location data is missing (double-check)
        if not all([current_user.latitude, current_user.longitude, 
                   match.latitude, match.longitude]):
            print(f"    ❌ Skipping {match.name} - missing location data")
            continue
            
        # Calculate distance
        user_location = (current_user.latitude, current_user.longitude)
        match_location = (match.latitude, match.longitude)
        distance = geodesic(user_location, match_location).kilometers
        
        # Skip if too far
        if distance > max_distance_km:
            print(f"    ❌ Skipping {match.name} - too far ({distance:.2f} km > {max_distance_km} km)")
            continue
            
        # Calculate match score
        match_score = calculate_match_score(current_user, match)
        
        # Only include matches above minimum score
        if match_score >= min_match_score:
            print(f"    ✅ {match.name} - Score: {match_score}, Distance: {distance:.2f} km")
            matches_with_scores.append((match, match_score))
        else:
            print(f"    ❌ Skipping {match.name} - score too low ({match_score} < {min_match_score})")
    
    # Sort by match score (highest first)
    matches_with_scores.sort(key=lambda x: x[1], reverse=True)
    
    print(f"🎯 Final matches for {current_user.name}: {len(matches_with_scores)} users")
    for match, score in matches_with_scores:
        print(f"  🏆 {match.name} (ID: {match.id}) - Score: {score}")
    
    return matches_with_scores
