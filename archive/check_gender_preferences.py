#!/usr/bin/env python3
"""
Check gender preferences to verify if users should be potential matches
"""

import asyncio
import os
import sys
from sqlalchemy.future import select

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.database import get_db
from app.models import User

async def check_gender_preferences():
    """Check gender preferences for Juan Baek and Junlin Yi"""
    
    print("🔍 Checking gender preferences for potential matches...")
    print("=" * 60)
    
    db = await anext(get_db())
    
    # Get Juan Baek's data
    juan_result = await db.execute(select(User).where(User.firebase_uid == "ITnBfONkfab6UUCxr2CwXeLdA8A2"))
    juan = juan_result.scalar_one()
    
    # Get Junlin Yi's data
    junlin_result = await db.execute(select(User).where(User.firebase_uid == "h0gWfJIdx8NSiqXnbcJcGoQ1uXY2"))
    junlin = junlin_result.scalar_one()
    
    print(f"👤 Juan Baek:")
    print(f"  - Gender: {juan.gender}")
    print(f"  - Preferred Gender: {juan.preferred_gender}")
    print(f"  - Age: {juan.age}")
    print(f"  - Min Age Preference: {juan.min_age_preference}")
    print(f"  - Max Age Preference: {juan.max_age_preference}")
    print()
    
    print(f"👤 Junlin Yi:")
    print(f"  - Gender: {junlin.gender}")
    print(f"  - Preferred Gender: {junlin.preferred_gender}")
    print(f"  - Age: {junlin.age}")
    print(f"  - Min Age Preference: {junlin.min_age_preference}")
    print(f"  - Max Age Preference: {junlin.max_age_preference}")
    print()
    
    # Check if they should match based on gender preferences
    print("🔍 Gender Preference Analysis:")
    
    # Juan's preference check
    juan_wants_junlin = juan.preferred_gender in [junlin.gender, "any"]
    print(f"  Juan wants Junlin's gender ({junlin.gender}): {juan_wants_junlin}")
    
    # Junlin's preference check
    junlin_wants_juan = junlin.preferred_gender in [juan.gender, "any"]
    print(f"  Junlin wants Juan's gender ({juan.gender}): {junlin_wants_juan}")
    
    # Mutual preference check
    mutual_match = juan_wants_junlin and junlin_wants_juan
    print(f"  Mutual gender preference match: {mutual_match}")
    print()
    
    # Age preference check
    print("🔍 Age Preference Analysis:")
    juan_age_ok = juan.min_age_preference <= junlin.age <= juan.max_age_preference
    junlin_age_ok = junlin.min_age_preference <= juan.age <= junlin.max_age_preference
    print(f"  Juan's age range ({juan.min_age_preference}-{juan.max_age_preference}) includes Junlin ({junlin.age}): {juan_age_ok}")
    print(f"  Junlin's age range ({junlin.min_age_preference}-{junlin.max_age_preference}) includes Juan ({juan.age}): {junlin_age_ok}")
    
    mutual_age_match = juan_age_ok and junlin_age_ok
    print(f"  Mutual age preference match: {mutual_age_match}")
    print()
    
    # Overall compatibility
    overall_compatible = mutual_match and mutual_age_match
    print(f"🎯 Overall compatibility: {overall_compatible}")
    
    if not overall_compatible:
        print("❌ They should NOT be potential matches!")
        if not mutual_match:
            print("   - Gender preferences don't match")
        if not mutual_age_match:
            print("   - Age preferences don't match")
    else:
        print("✅ They should be potential matches!")
    
    await db.close()

if __name__ == "__main__":
    asyncio.run(check_gender_preferences()) 