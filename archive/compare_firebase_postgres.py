#!/usr/bin/env python3

import asyncio
import firebase_admin
from firebase_admin import credentials, firestore
from sqlalchemy import text
from app.database import get_db

async def compare_firebase_postgres():
    """Compare data between Firebase and PostgreSQL"""
    
    # Initialize Firebase with service account
    if not firebase_admin._apps:
        cred = credentials.Certificate("facedate-6616e-ebf102022977.json")
        firebase_admin.initialize_app(cred)
    
    firestore_db = firestore.client()
    
    print("=== COMPARING FIREBASE vs POSTGRESQL ===")
    
    # Get database session
    db = await anext(get_db())
    
    try:
        # 1. Compare Users
        print("\n" + "="*50)
        print("USERS COMPARISON")
        print("="*50)
        
        # Get Firebase users
        users_ref = firestore_db.collection('users')
        firebase_users = list(users_ref.stream())
        
        print(f"\n🔥 FIREBASE USERS ({len(firebase_users)} total):")
        firebase_uids = []
        for user in firebase_users:
            user_data = user.to_dict()
            firebase_uid = user.id
            firebase_uids.append(firebase_uid)
            print(f"   - UID: {firebase_uid}")
            print(f"     Name: {user_data.get('name', 'Unknown')}")
            print(f"     Email: {user_data.get('email', 'Unknown')}")
            print(f"     Age: {user_data.get('age', 'Unknown')}")
            print(f"     Gender: {user_data.get('gender', 'Unknown')}")
        
        # Get PostgreSQL users
        result = await db.execute(text("SELECT firebase_uid, name, email, age, gender FROM users ORDER BY id"))
        pg_users = result.fetchall()
        
        print(f"\n🐘 POSTGRESQL USERS ({len(pg_users)} total):")
        pg_uids = []
        for user in pg_users:
            firebase_uid, name, email, age, gender = user
            pg_uids.append(firebase_uid)
            print(f"   - UID: {firebase_uid}")
            print(f"     Name: {name or 'Unknown'}")
            print(f"     Email: {email or 'Unknown'}")
            print(f"     Age: {age or 'Unknown'}")
            print(f"     Gender: {gender or 'Unknown'}")
        
        # Compare user counts
        print(f"\n📊 USER COMPARISON:")
        print(f"   Firebase users: {len(firebase_users)}")
        print(f"   PostgreSQL users: {len(pg_users)}")
        
        # Find missing users
        firebase_only = set(firebase_uids) - set(pg_uids)
        postgres_only = set(pg_uids) - set(firebase_uids)
        
        if firebase_only:
            print(f"   ❌ Users in Firebase but NOT in PostgreSQL: {list(firebase_only)}")
        if postgres_only:
            print(f"   ❌ Users in PostgreSQL but NOT in Firebase: {list(postgres_only)}")
        if not firebase_only and not postgres_only:
            print(f"   ✅ All users are synced between Firebase and PostgreSQL!")
        
        # 2. Compare Matches/Conversations
        print("\n" + "="*50)
        print("MATCHES/CONVERSATIONS COMPARISON")
        print("="*50)
        
        # Get Firebase matches
        matches_ref = firestore_db.collection('matches')
        firebase_matches = list(matches_ref.stream())
        
        print(f"\n🔥 FIREBASE MATCHES ({len(firebase_matches)} total):")
        for match in firebase_matches:
            match_data = match.to_dict()
            print(f"   - Match ID: {match.id}")
            print(f"     Users: {match_data.get('users', [])}")
            print(f"     Status: {match_data.get('status', 'unknown')}")
            print(f"     Last Message: {match_data.get('lastMessage', 'None')}")
        
        # Get PostgreSQL conversations
        result = await db.execute(text("""
            SELECT c.id, c.user1_id, c.user2_id, c.created_at, c.last_message, c.last_message_at,
                   u1.firebase_uid as user1_uid, u2.firebase_uid as user2_uid,
                   u1.name as user1_name, u2.name as user2_name
            FROM conversations c
            JOIN users u1 ON c.user1_id = u1.id
            JOIN users u2 ON c.user2_id = u2.id
            ORDER BY c.created_at DESC
        """))
        pg_conversations = result.fetchall()
        
        print(f"\n🐘 POSTGRESQL CONVERSATIONS ({len(pg_conversations)} total):")
        for conv in pg_conversations:
            conv_id, user1_id, user2_id, created_at, last_message, last_message_at, user1_uid, user2_uid, user1_name, user2_name = conv
            print(f"   - Conversation ID: {conv_id}")
            print(f"     Users: [{user1_uid}, {user2_uid}] ({user1_name} & {user2_name})")
            print(f"     Created: {created_at}")
            print(f"     Last Message: {last_message or 'None'}")
            print(f"     Last Message At: {last_message_at or 'None'}")
        
        # 3. Compare Messages
        print("\n" + "="*50)
        print("MESSAGES COMPARISON")
        print("="*50)
        
        # Get Firebase messages
        chats_ref = firestore_db.collection('chats')
        chat_rooms = list(chats_ref.stream())
        
        total_firebase_messages = 0
        print(f"\n🔥 FIREBASE MESSAGES:")
        for chat in chat_rooms:
            messages_ref = chat.reference.collection('messages')
            messages = list(messages_ref.stream())
            total_firebase_messages += len(messages)
            if messages:
                print(f"   - Chat Room: {chat.id}")
                print(f"     Messages: {len(messages)}")
                for msg in messages[:3]:  # Show first 3 messages
                    msg_data = msg.to_dict()
                    print(f"       * {msg_data.get('content', 'No content')[:50]}...")
        
        print(f"   Total Firebase messages: {total_firebase_messages}")
        
        # Get PostgreSQL messages
        result = await db.execute(text("SELECT COUNT(*) FROM messages"))
        pg_message_count = result.scalar()
        
        print(f"\n🐘 POSTGRESQL MESSAGES: {pg_message_count} total")
        
        # 4. Summary
        print("\n" + "="*50)
        print("SUMMARY")
        print("="*50)
        
        print(f"\n📊 DATA SUMMARY:")
        print(f"   Users: Firebase={len(firebase_users)}, PostgreSQL={len(pg_users)}")
        print(f"   Matches: Firebase={len(firebase_matches)}, PostgreSQL={len(pg_conversations)}")
        print(f"   Messages: Firebase={total_firebase_messages}, PostgreSQL={pg_message_count}")
        
        if len(firebase_users) == len(pg_users) and len(firebase_matches) == len(pg_conversations):
            print(f"\n✅ SYNC STATUS: All data appears to be in sync!")
        else:
            print(f"\n⚠️  SYNC STATUS: Data appears to be out of sync")
            print(f"   Run: curl -X POST http://localhost:8000/sync/all")
        
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(compare_firebase_postgres()) 