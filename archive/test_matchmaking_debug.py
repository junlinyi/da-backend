#!/usr/bin/env python3

import asyncio
from sqlalchemy import create_engine, text
from app.database import get_db
from app.models import User
from app.services.matchmaking import find_matches, calculate_match_score
from geopy.distance import geodesic

async def main():
    # Get database session
    db = await anext(get_db())
    
    try:
        # Get all users with complete profiles
        result = await db.execute(text("""
            SELECT id, firebase_uid, name, age, gender, preferred_gender, 
                   min_age_preference, max_age_preference, latitude, longitude, interests, max_distance_km
            FROM users
            WHERE name IS NOT NULL 
              AND age IS NOT NULL 
              AND gender IS NOT NULL 
              AND preferred_gender IS NOT NULL
              AND latitude IS NOT NULL 
              AND longitude IS NOT NULL
        """))
        users = result.fetchall()
        
        print("=== USERS WITH COMPLETE PROFILES ===")
        for user in users:
            print(f"ID: {user[0]}, UID: {user[1]}, Name: {user[2]}, Age: {user[3]}, "
                  f"Gender: {user[4]}, Pref: {user[5]}, Age Range: {user[6]}-{user[7]}, "
                  f"Location: ({user[8]}, {user[9]}), Interests: {user[10]}, Max Distance: {user[11]} km")
        
        if len(users) < 2:
            print("\n❌ Need at least 2 users with complete profiles for matchmaking!")
            return
        
        print("\n=== MATCHMAKING ANALYSIS ===")
        
        # Test matchmaking for each user using the actual matchmaking service
        for user_data in users:
            user_id = user_data[0]
            user_name = user_data[2]
            user_max_distance = user_data[11]
            
            print(f"\n--- Testing matches for {user_name} (ID: {user_id}, Max Distance: {user_max_distance} km) ---")
            
            # Use the actual matchmaking service
            matches_with_scores = await find_matches(user_id, db)
            
            if matches_with_scores:
                print(f"  Found {len(matches_with_scores)} potential matches:")
                for match, score in matches_with_scores:
                    print(f"    ✅ {match.name} (Score: {score})")
            else:
                print("  ❌ No potential matches found")
                
                # Let's analyze why no matches were found
                print("  Analyzing potential issues:")
                
                # Check each other user as potential match
                for other_user_data in users:
                    if other_user_data[0] == user_id:
                        continue
                        
                    other_user = type('User', (), {
                        'id': other_user_data[0],
                        'age': other_user_data[3],
                        'gender': other_user_data[4],
                        'preferred_gender': other_user_data[5],
                        'min_age_preference': other_user_data[6],
                        'max_age_preference': other_user_data[7],
                        'latitude': other_user_data[8],
                        'longitude': other_user_data[9],
                        'interests': other_user_data[10] or []
                    })()
                    
                    current_user = type('User', (), {
                        'id': user_data[0],
                        'age': user_data[3],
                        'gender': user_data[4],
                        'preferred_gender': user_data[5],
                        'min_age_preference': user_data[6],
                        'max_age_preference': user_data[7],
                        'latitude': user_data[8],
                        'longitude': user_data[9],
                        'interests': user_data[10] or []
                    })()
                    
                    print(f"\n    Checking {other_user_data[2]}:")
                    
                    # Check basic criteria
                    gender_match = (other_user.gender == current_user.preferred_gender or 
                                  current_user.preferred_gender == "any")
                    age_match = (current_user.min_age_preference <= other_user.age <= current_user.max_age_preference)
                    
                    print(f"      Gender match: {gender_match} (prefers {current_user.preferred_gender}, is {other_user.gender})")
                    print(f"      Age match: {age_match} (prefers {current_user.min_age_preference}-{current_user.max_age_preference}, is {other_user.age})")
                    
                    if not (gender_match and age_match):
                        print("      ❌ Basic criteria not met")
                        continue
                    
                    # Check distance
                    distance = geodesic(
                        (current_user.latitude, current_user.longitude),
                        (other_user.latitude, other_user.longitude)
                    ).kilometers
                    print(f"      Distance: {distance:.2f} km (max allowed: {user_max_distance} km)")
                    
                    if distance > user_max_distance:
                        print(f"      ❌ Too far (> {user_max_distance} km)")
                        continue
                    
                    # Calculate match score
                    match_score = calculate_match_score(current_user, other_user)
                    print(f"      ✅ Match score: {match_score}")
                    
                    if match_score >= 0.3:  # min_match_score
                        print(f"      🎯 SHOULD BE A MATCH! Score: {match_score}")
                    else:
                        print(f"      ❌ Score too low: {match_score}")
        
        print("\n=== DETAILED USER ANALYSIS ===")
        # Let's also check ALL users, including incomplete ones
        all_users_result = await db.execute(text("""
            SELECT id, firebase_uid, name, age, gender, preferred_gender, 
                   min_age_preference, max_age_preference, latitude, longitude, interests, max_distance_km
            FROM users
            ORDER BY id
        """))
        all_users = all_users_result.fetchall()
        
        print("=== ALL USERS (including incomplete) ===")
        for user in all_users:
            print(f"ID: {user[0]}, UID: {user[1]}, Name: \"{user[2]}\", Age: {user[3]}, "
                  f"Gender: {user[4]}, Pref: {user[5]}, Age Range: {user[6]}-{user[7]}, "
                  f"Location: ({user[8]}, {user[9]}), Interests: {user[10]}, Max Distance: {user[11]} km")
    
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(main()) 