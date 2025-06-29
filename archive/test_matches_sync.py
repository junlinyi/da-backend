#!/usr/bin/env python3
"""
Test script to verify matches table sync from Firebase
"""

import asyncio
import os
import sys
from datetime import datetime
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.database import get_db
from app.models import User, Match, Conversation
from app.services.firebase_sync_service import FirebaseSyncService

async def test_matches_sync():
    """Test if matches table is being synced from Firebase"""
    
    print("🔍 Testing Firebase to PostgreSQL matches sync...")
    print("=" * 60)
    
    # Initialize Firebase sync service
    sync_service = FirebaseSyncService()
    
    # Get Firebase matches
    print("📊 Firebase Matches:")
    print("-" * 30)
    firebase_matches = []
    matches_ref = sync_service.firestore_db.collection('matches')
    for match_doc in matches_ref.stream():
        match_data = match_doc.to_dict()
        users = match_data.get('users', [])
        if len(users) == 2:
            firebase_matches.append({
                'id': match_doc.id,
                'users': users,
                'lastMessage': match_data.get('lastMessage'),
                'lastUpdated': match_data.get('lastUpdated'),
                'createdAt': match_data.get('createdAt')
            })
            print(f"  Match {match_doc.id}: {users[0]} ↔ {users[1]}")
            print(f"    Last message: {match_data.get('lastMessage', 'None')}")
            print(f"    Last updated: {match_data.get('lastUpdated', 'None')}")
            print()
    
    print(f"Total Firebase matches: {len(firebase_matches)}")
    print()
    
    # Get PostgreSQL matches
    print("🗄️  PostgreSQL Matches Table:")
    print("-" * 30)
    db = await anext(get_db())
    
    # Get all matches
    matches_result = await db.execute(select(Match))
    matches = matches_result.scalars().all()
    
    for match in matches:
        # Get user names
        user1_result = await db.execute(select(User).where(User.id == match.user_id))
        user1 = user1_result.scalar_one()
        
        user2_result = await db.execute(select(User).where(User.id == match.matched_user_id))
        user2 = user2_result.scalar_one()
        
        print(f"  Match ID: {match.id}")
        print(f"    Users: {user1.name} (ID: {match.user_id}) ↔ {user2.name} (ID: {match.matched_user_id})")
        print(f"    Score: {match.match_score:.2f}")
        print(f"    Status: {match.status}")
        print(f"    Created: {match.created_at}")
        print()
    
    print(f"Total PostgreSQL matches: {len(matches)}")
    print()
    
    # Get PostgreSQL conversations for comparison
    print("💬 PostgreSQL Conversations Table:")
    print("-" * 30)
    conversations_result = await db.execute(select(Conversation))
    conversations = conversations_result.scalars().all()
    
    for conv in conversations:
        # Get user names
        user1_result = await db.execute(select(User).where(User.id == conv.user1_id))
        user1 = user1_result.scalar_one()
        
        user2_result = await db.execute(select(User).where(User.id == conv.user2_id))
        user2 = user2_result.scalar_one()
        
        print(f"  Conversation ID: {conv.id}")
        print(f"    Users: {user1.name} (ID: {conv.user1_id}) ↔ {user2.name} (ID: {conv.user2_id})")
        print(f"    Last message: {conv.last_message}")
        print(f"    Last message at: {conv.last_message_at}")
        print()
    
    print(f"Total PostgreSQL conversations: {len(conversations)}")
    print()
    
    # Check for consistency
    print("✅ Consistency Check:")
    print("-" * 30)
    
    if len(firebase_matches) == len(conversations):
        print(f"✅ Firebase matches ({len(firebase_matches)}) = PostgreSQL conversations ({len(conversations)})")
    else:
        print(f"❌ Mismatch: Firebase matches ({len(firebase_matches)}) ≠ PostgreSQL conversations ({len(conversations)})")
    
    if len(matches) > 0:
        print(f"✅ Matches table populated with {len(matches)} records for analytics")
    else:
        print(f"❌ Matches table is empty - sync may not be working")
    
    # Check if all Firebase matches have corresponding PostgreSQL records
    firebase_user_pairs = set()
    for match in firebase_matches:
        users = sorted(match['users'])
        firebase_user_pairs.add(tuple(users))
    
    pg_user_pairs = set()
    for conv in conversations:
        user1_result = await db.execute(select(User).where(User.id == conv.user1_id))
        user1 = user1_result.scalar_one()
        user2_result = await db.execute(select(User).where(User.id == conv.user2_id))
        user2 = user2_result.scalar_one()
        
        users = sorted([user1.firebase_uid, user2.firebase_uid])
        pg_user_pairs.add(tuple(users))
    
    if firebase_user_pairs == pg_user_pairs:
        print("✅ All Firebase matches have corresponding PostgreSQL records")
    else:
        missing = firebase_user_pairs - pg_user_pairs
        extra = pg_user_pairs - firebase_user_pairs
        if missing:
            print(f"❌ Missing in PostgreSQL: {missing}")
        if extra:
            print(f"❌ Extra in PostgreSQL: {extra}")
    
    await db.close()
    print()
    print("🎯 Test completed!")

if __name__ == "__main__":
    asyncio.run(test_matches_sync()) 