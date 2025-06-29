#!/usr/bin/env python3
"""
Fix Firebase data by adding ages from PostgreSQL and fixing location structure
"""

import asyncio
import os
import sys
import firebase_admin
from firebase_admin import firestore
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

async def fix_firebase_data():
    """Fix Firebase data using PostgreSQL as source of truth"""
    
    print("🔧 Fixing Firebase data...")
    print("=" * 50)
    
    # Initialize Firebase
    try:
        firebase_admin.get_app()
    except ValueError:
        cred = firebase_admin.credentials.Certificate("facedate-6616e-ebf102022977.json")
        firebase_admin.initialize_app(cred)
    
    firestore_db = firestore.client()
    
    # Initialize PostgreSQL connection using correct credentials
    DATABASE_URL = "postgresql+asyncpg://dating_user:securepassword@localhost/dating_app"
    engine = create_async_engine(DATABASE_URL)
    
    async with engine.begin() as conn:
        # Get all users from PostgreSQL with their ages
        result = await conn.execute(text("""
            SELECT firebase_uid, name, age, latitude, longitude
            FROM users 
            WHERE firebase_uid IS NOT NULL
        """))
        pg_users = result.fetchall()
        
        print(f"📊 Found {len(pg_users)} users in PostgreSQL")
        
        # Create a mapping of firebase_uid to PostgreSQL data
        pg_data = {row.firebase_uid: {
            'name': row.name,
            'age': row.age,
            'latitude': row.latitude,
            'longitude': row.longitude
        } for row in pg_users}
    
    # Get all users from Firebase
    users_ref = firestore_db.collection('users')
    firebase_users = users_ref.stream()
    
    updates_made = 0
    
    for user_doc in firebase_users:
        firebase_uid = user_doc.id
        user_data = user_doc.to_dict()
        
        print(f"\n👤 Processing: {user_data.get('name', 'Unknown')} ({firebase_uid})")
        
        # Check if user exists in PostgreSQL
        if firebase_uid not in pg_data:
            print(f"  ⚠️  User not found in PostgreSQL, skipping...")
            continue
        
        pg_user = pg_data[firebase_uid]
        updates = {}
        
        # Check if age needs to be added
        if 'age' not in user_data or user_data['age'] is None:
            updates['age'] = pg_user['age']
            print(f"  ✅ Adding age: {pg_user['age']}")
        
        # Check if location structure needs to be fixed
        current_location = user_data.get('location', {})
        current_lat = user_data.get('latitude')
        current_lng = user_data.get('longitude')
        
        # If we have a location object but no separate lat/lng fields
        if current_location and isinstance(current_location, dict):
            if 'latitude' in current_location and 'longitude' in current_location:
                # Extract lat/lng from location object
                updates['latitude'] = current_location['latitude']
                updates['longitude'] = current_location['longitude']
                # Remove the nested location object
                updates['location'] = firestore.DELETE_FIELD
                print(f"  ✅ Fixed location structure: lat={current_location['latitude']}, lng={current_location['longitude']}")
        
        # If we don't have lat/lng fields but should have them from PostgreSQL
        elif current_lat is None or current_lng is None:
            if pg_user['latitude'] is not None and pg_user['longitude'] is not None:
                updates['latitude'] = pg_user['latitude']
                updates['longitude'] = pg_user['longitude']
                print(f"  ✅ Adding location from PostgreSQL: lat={pg_user['latitude']}, lng={pg_user['longitude']}")
        
        # Apply updates if any
        if updates:
            try:
                users_ref.document(firebase_uid).update(updates)
                updates_made += 1
                print(f"  ✅ Updated Firebase document")
            except Exception as e:
                print(f"  ❌ Error updating Firebase: {e}")
        else:
            print(f"  ✅ No updates needed")
    
    await engine.dispose()
    
    print(f"\n" + "=" * 50)
    print(f"🎯 Summary: Updated {updates_made} Firebase documents")
    print("Done.")

if __name__ == "__main__":
    asyncio.run(fix_firebase_data()) 