#!/usr/bin/env python3
"""
Compare Firebase and PostgreSQL data for Juan Baek
"""

import asyncio
import os
import sys
from sqlalchemy.future import select
import firebase_admin
from firebase_admin import firestore

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.database import get_db
from app.models import User

async def check_firebase_vs_postgres():
    """Compare Firebase and PostgreSQL data for Juan Baek"""
    
    print("🔍 Comparing Firebase vs PostgreSQL data for Juan Baek...")
    print("=" * 60)
    
    # Initialize Firebase
    try:
        firebase_admin.get_app()
    except ValueError:
        cred = firebase_admin.credentials.Certificate("facedate-6616e-ebf102022977.json")
        firebase_admin.initialize_app(cred)
    
    firestore_db = firestore.client()
    
    # Juan Baek's Firebase UID
    juan_firebase_uid = "ITnBfONkfab6UUCxr2CwXeLdA8A2"
    
    # Get Firebase data
    print("📊 Firebase Data:")
    print("-" * 30)
    try:
        firebase_user_doc = firestore_db.collection('users').document(juan_firebase_uid).get()
        if firebase_user_doc.exists:
            firebase_data = firebase_user_doc.to_dict()
            print(f"  Name: {firebase_data.get('name', 'N/A')}")
            print(f"  Age: {firebase_data.get('age', 'N/A')}")
            print(f"  Gender: {firebase_data.get('gender', 'N/A')}")
            print(f"  Preferred Gender: {firebase_data.get('preferredGender', 'N/A')}")
            print(f"  Min Age Preference: {firebase_data.get('minAgePreference', 'N/A')}")
            print(f"  Max Age Preference: {firebase_data.get('maxAgePreference', 'N/A')}")
            print(f"  Location: {firebase_data.get('location', 'N/A')}")
            print(f"  Latitude: {firebase_data.get('latitude', 'N/A')}")
            print(f"  Longitude: {firebase_data.get('longitude', 'N/A')}")
            print(f"  Interests: {firebase_data.get('interests', 'N/A')}")
            print(f"  Bio: {firebase_data.get('bio', 'N/A')}")
        else:
            print("  ❌ User not found in Firebase")
    except Exception as e:
        print(f"  ❌ Error getting Firebase data: {e}")
    
    print()
    
    # Get PostgreSQL data
    print("🗄️  PostgreSQL Data:")
    print("-" * 30)
    try:
        db = await anext(get_db())
        result = await db.execute(select(User).where(User.firebase_uid == juan_firebase_uid))
        postgres_user = result.scalar_one()
        
        if postgres_user:
            print(f"  Name: {postgres_user.name}")
            print(f"  Age: {postgres_user.age}")
            print(f"  Gender: {postgres_user.gender}")
            print(f"  Preferred Gender: {postgres_user.preferred_gender}")
            print(f"  Min Age Preference: {postgres_user.min_age_preference}")
            print(f"  Max Age Preference: {postgres_user.max_age_preference}")
            print(f"  Location: {postgres_user.location}")
            print(f"  Latitude: {postgres_user.latitude}")
            print(f"  Longitude: {postgres_user.longitude}")
            print(f"  Interests: {postgres_user.interests}")
            print(f"  Bio: {postgres_user.bio}")
        else:
            print("  ❌ User not found in PostgreSQL")
    except Exception as e:
        print(f"  ❌ Error getting PostgreSQL data: {e}")
    
    print()
    
    # Compare key fields
    print("🔍 Comparison Analysis:")
    print("-" * 30)
    
    if firebase_user_doc.exists and postgres_user:
        firebase_data = firebase_user_doc.to_dict()
        
        # Compare key fields
        fields_to_compare = [
            ('name', 'name'),
            ('age', 'age'),
            ('gender', 'gender'),
            ('preferredGender', 'preferred_gender'),
            ('minAgePreference', 'min_age_preference'),
            ('maxAgePreference', 'max_age_preference'),
            ('location', 'location'),
            ('latitude', 'latitude'),
            ('longitude', 'longitude')
        ]
        
        mismatches = []
        for firebase_field, postgres_field in fields_to_compare:
            firebase_value = firebase_data.get(firebase_field)
            postgres_value = getattr(postgres_user, postgres_field)
            
            if firebase_value != postgres_value:
                mismatches.append((firebase_field, firebase_value, postgres_value))
                print(f"  ❌ {firebase_field}: Firebase={firebase_value}, PostgreSQL={postgres_value}")
            else:
                print(f"  ✅ {firebase_field}: {firebase_value}")
        
        if mismatches:
            print(f"\n🎯 Found {len(mismatches)} mismatches!")
            print("   PostgreSQL needs to be synced with Firebase data.")
        else:
            print(f"\n🎯 All fields match! Data is in sync.")
    
    print("\nDone.")

if __name__ == "__main__":
    asyncio.run(check_firebase_vs_postgres()) 