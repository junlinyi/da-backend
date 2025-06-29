#!/usr/bin/env python3

import asyncio
from sqlalchemy import create_engine, text
from app.database import get_db
import firebase_admin
from firebase_admin import firestore

async def check_conversations():
    # Initialize Firebase
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    
    firestore_db = firestore.client()
    
    # Get database session
    db = await anext(get_db())
    
    try:
        # Check PostgreSQL conversations
        print("=== POSTGRESQL CONVERSATIONS ===")
        result = await db.execute(text("SELECT * FROM conversations ORDER BY created_at DESC LIMIT 5"))
        pg_conversations = result.fetchall()
        
        if pg_conversations:
            for conv in pg_conversations:
                print(f"ID: {conv[0]}, User1: {conv[1]}, User2: {conv[2]}, Created: {conv[3]}")
        else:
            print("No conversations found in PostgreSQL")
        
        # Check Firebase matches
        print("\n=== FIREBASE MATCHES ===")
        matches_ref = firestore_db.collection('matches')
        firebase_matches = matches_ref.stream()
        
        firebase_count = 0
        for match in firebase_matches:
            firebase_count += 1
            match_data = match.to_dict()
            print(f"Match ID: {match.id}")
            print(f"  Users: {match_data.get('users', [])}")
            print(f"  Status: {match_data.get('status', 'unknown')}")
            print(f"  Last Message: {match_data.get('lastMessage', 'none')}")
            print(f"  Last Updated: {match_data.get('lastUpdated', 'none')}")
            print()
            
            if firebase_count >= 5:
                break
        
        if firebase_count == 0:
            print("No matches found in Firebase")
            
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(check_conversations()) 