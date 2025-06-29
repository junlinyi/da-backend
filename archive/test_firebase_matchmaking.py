#!/usr/bin/env python3
"""
Test the new Firebase-based matchmaking service
"""

import asyncio
import os
import sys
from datetime import datetime

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.services.firebase_matchmaking import FirebaseMatchmakingService
from app.database import get_db

async def test_firebase_matchmaking():
    """Test the Firebase-based matchmaking service"""
    
    print("🧪 Testing Firebase-based matchmaking service...")
    print("=" * 60)
    
    try:
        # Initialize the service
        firebase_service = FirebaseMatchmakingService()
        
        # Test with a known user (Juan Baek)
        test_user_firebase_uid = "ITnBfONkfab6UUCxr2CwXeLdA8A2"
        
        print(f"🔍 Testing matchmaking for user: {test_user_firebase_uid}")
        
        # Get database session
        db = await anext(get_db())
        
        # Get potential matches
        result = await firebase_service.get_potential_matches_realtime(
            test_user_firebase_uid, 
            db, 
            max_results=5
        )
        
        print(f"✅ Successfully got potential matches!")
        print(f"📊 Results:")
        print(f"  - Total matches found: {len(result['matches'])}")
        print(f"  - Remaining swipes: {result['remainingSwipes']}")
        print()
        
        # Display matches
        for i, match in enumerate(result['matches'], 1):
            print(f"  {i}. {match['name']} (Age: {match['age']}, Gender: {match['gender']})")
            print(f"     Score: {match['matchScore']:.2f}")
            print(f"     Location: {match['location']['city'] if match['location'] else 'Unknown'}")
            print(f"     Interests: {', '.join(match['interests'][:3]) if match['interests'] else 'None'}")
            print()
        
        await db.close()
        
        print("🎯 Test completed successfully!")
        
    except Exception as e:
        print(f"❌ Error testing Firebase matchmaking: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_firebase_matchmaking()) 