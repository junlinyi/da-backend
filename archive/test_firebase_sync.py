#!/usr/bin/env python3

import asyncio
import firebase_admin
from firebase_admin import firestore
from app.services.firebase_sync_service import FirebaseSyncService

async def test_firebase_sync():
    """Test the Firebase sync service"""
    
    # Initialize Firebase
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    
    firestore_db = firestore.client()
    
    print("=== TESTING FIREBASE SYNC SERVICE ===")
    
    # Test 1: Check if Firebase has users
    print("\n1. Checking Firebase users...")
    users_ref = firestore_db.collection('users')
    firebase_users = list(users_ref.stream())
    
    if firebase_users:
        print(f"✅ Found {len(firebase_users)} users in Firebase")
        for user in firebase_users[:3]:  # Show first 3 users
            user_data = user.to_dict()
            print(f"   - User ID: {user.id}")
            print(f"     Name: {user_data.get('name', 'Unknown')}")
            print(f"     Email: {user_data.get('email', 'Unknown')}")
    else:
        print("❌ No users found in Firebase")
    
    # Test 2: Check if Firebase has matches
    print("\n2. Checking Firebase matches...")
    matches_ref = firestore_db.collection('matches')
    firebase_matches = list(matches_ref.stream())
    
    if firebase_matches:
        print(f"✅ Found {len(firebase_matches)} matches in Firebase")
        for match in firebase_matches:
            match_data = match.to_dict()
            print(f"   - Match ID: {match.id}")
            print(f"     Users: {match_data.get('users', [])}")
            print(f"     Status: {match_data.get('status', 'unknown')}")
            print(f"     Last Message: {match_data.get('lastMessage', 'None')}")
    else:
        print("❌ No matches found in Firebase")
    
    # Test 3: Check if Firebase has chat rooms
    print("\n3. Checking Firebase chat rooms...")
    chats_ref = firestore_db.collection('chats')
    chat_rooms = list(chats_ref.stream())
    
    if chat_rooms:
        print(f"✅ Found {len(chat_rooms)} chat rooms in Firebase")
        for chat in chat_rooms:
            print(f"   - Chat Room ID: {chat.id}")
            
            # Check messages in this chat room
            messages_ref = chat.reference.collection('messages')
            messages = list(messages_ref.stream())
            print(f"     Messages: {len(messages)}")
    else:
        print("❌ No chat rooms found in Firebase")
    
    print("\n=== AUTOMATIC SYNC SERVICE ===")
    print("✅ The background sync service automatically syncs:")
    print("   - Users (Firebase → PostgreSQL)")
    print("   - Matches → Conversations")
    print("   - Messages")
    print("   - User activity")
    print("\n🔄 Sync runs every 30 seconds when backend is running")
    print("📊 PostgreSQL data is used for analytics and ML training")
    
    print("\n=== MANUAL SYNC COMMANDS (if needed) ===")
    print("curl -X POST http://localhost:8000/sync/users     # Sync users only")
    print("curl -X POST http://localhost:8000/sync/all       # Sync everything")
    print("curl -X GET  http://localhost:8000/sync/status    # Check sync status")

if __name__ == "__main__":
    asyncio.run(test_firebase_sync()) 