#!/usr/bin/env python3
"""
Test the updated API endpoint with Firebase-based matchmaking
"""

import asyncio
import os
import sys
import httpx
from datetime import datetime

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

async def test_api_endpoint():
    """Test the potential-matches API endpoint"""
    
    print("🧪 Testing API endpoint with Firebase-based matchmaking...")
    print("=" * 60)
    
    # Test user (Juan Baek)
    test_user_firebase_uid = "ITnBfONkfab6UUCxr2CwXeLdA8A2"
    
    # API endpoint
    base_url = "http://localhost:8000"
    endpoint = f"{base_url}/api/matchmaking/potential-matches?user_id={test_user_firebase_uid}"
    
    print(f"🔗 Testing endpoint: {endpoint}")
    print(f"👤 User: {test_user_firebase_uid}")
    print()
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Make the request
            start_time = datetime.now()
            response = await client.get(endpoint)
            end_time = datetime.now()
            
            response_time = (end_time - start_time).total_seconds() * 1000
            
            print(f"⏱️  Response time: {response_time:.2f}ms")
            print(f"📊 Status code: {response.status_code}")
            print()
            
            if response.status_code == 200:
                data = response.json()
                
                print(f"✅ Success! API Response:")
                print(f"  - Total matches: {len(data['matches'])}")
                print(f"  - Remaining swipes: {data['remainingSwipes']}")
                print()
                
                # Display matches
                for i, match in enumerate(data['matches'], 1):
                    print(f"  {i}. {match['name']} (Age: {match['age']}, Gender: {match['gender']})")
                    print(f"     Score: {match['matchScore']:.2f}")
                    print(f"     Location: {match['location']['city'] if match['location'] else 'Unknown'}")
                    print(f"     Interests: {', '.join(match['interests'][:3]) if match['interests'] else 'None'}")
                    print()
                
                print("🎯 API endpoint test completed successfully!")
                
            else:
                print(f"❌ Error: {response.status_code}")
                print(f"Response: {response.text}")
                
    except httpx.ConnectError:
        print("❌ Could not connect to the API server")
        print("Make sure the backend server is running on http://localhost:8000")
    except Exception as e:
        print(f"❌ Error testing API endpoint: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_api_endpoint()) 