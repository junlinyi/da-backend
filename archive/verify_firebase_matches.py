#!/usr/bin/env python3

import asyncio
from sqlalchemy import text
from app.database import get_db
import firebase_admin
from firebase_admin import firestore

async def verify_firebase_matches():
    # Initialize Firebase
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    
    firestore_db = firestore.client()
    
    # Get database session
    db = await anext(get_db())
    
    try:
        # Get PostgreSQL conversations with user details
        print("=== VERIFYING FIREBASE MATCHES ===")
        
        result = await db.execute(text("""
            SELECT c.id, c.user1_id, c.user2_id, c.created_at,
                   u1.firebase_uid as user1_firebase_uid, u1.name as user1_name,
                   u2.firebase_uid as user2_firebase_uid, u2.name as user2_name
            FROM conversations c
            JOIN users u1 ON c.user1_id = u1.id
            JOIN users u2 ON c.user2_id = u2.id
            ORDER BY c.created_at DESC
        """))
        
        conversations = result.fetchall()
        
        if not conversations:
            print("No conversations found in PostgreSQL")
            return
        
        print(f"Found {len(conversations)} conversations in PostgreSQL")
        print()
        
        # Check each conversation for corresponding Firebase match
        for conv in conversations:
            conv_id = conv[0]
            user1_firebase_uid = conv[4]
            user2_firebase_uid = conv[5]
            user1_name = conv[6]
            user2_name = conv[7]
            created_at = conv[3]
            
            print(f"Conversation {conv_id}: {user1_name} ↔ {user2_name}")
            print(f"  User1 Firebase UID: {user1_firebase_uid}")
            print(f"  User2 Firebase UID: {user2_firebase_uid}")
            print(f"  Created: {created_at}")
            
            # Check if match exists in Firebase
            matches_ref = firestore_db.collection('matches')
            
            # Query for matches containing both users
            matches = matches_ref.where('users', 'array_contains_any', [user1_firebase_uid, user2_firebase_uid]).stream()
            
            found_match = False
            for match in matches:
                match_data = match.to_dict()
                users = match_data.get('users', [])
                
                if user1_firebase_uid in users and user2_firebase_uid in users:
                    print(f"  ✅ Firebase match found: {match.id}")
                    print(f"     Status: {match_data.get('status', 'unknown')}")
                    print(f"     Last Message: {match_data.get('lastMessage', 'none')}")
                    print(f"     Last Updated: {match_data.get('lastUpdated', 'none')}")
                    found_match = True
                    break
            
            if not found_match:
                print(f"  ❌ No Firebase match found!")
                print(f"     Expected users: [{user1_firebase_uid}, {user2_firebase_uid}]")
            
            print()
            
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(verify_firebase_matches()) 