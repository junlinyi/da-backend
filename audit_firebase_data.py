#!/usr/bin/env python3
"""
Audit all Firebase user data for missing or inconsistent fields
"""

import asyncio
import os
import sys
import firebase_admin
from firebase_admin import firestore

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

async def audit_firebase_data():
    """Audit all Firebase user data"""
    
    print("🔍 Auditing all Firebase user data...")
    print("=" * 60)
    
    # Initialize Firebase
    try:
        firebase_admin.get_app()
    except ValueError:
        cred = firebase_admin.credentials.Certificate("facedate-6616e-ebf102022977.json")
        firebase_admin.initialize_app(cred)
    
    firestore_db = firestore.client()
    
    # Get all users from Firebase
    users_ref = firestore_db.collection('users')
    firebase_users = users_ref.stream()
    
    print("📊 Firebase User Data Audit:")
    print("-" * 40)
    
    users_data = []
    missing_fields = {
        'name': [],
        'age': [],
        'gender': [],
        'preferredGender': [],
        'minAgePreference': [],
        'maxAgePreference': [],
        'location': [],
        'latitude': [],
        'longitude': [],
        'interests': [],
        'bio': [],
        'email': []
    }
    
    for user_doc in firebase_users:
        user_data = user_doc.to_dict()
        firebase_uid = user_doc.id
        
        users_data.append({
            'firebase_uid': firebase_uid,
            'data': user_data
        })
        
        print(f"\n👤 {user_data.get('name', 'Unknown')} (UID: {firebase_uid})")
        
        # Check each field
        for field in missing_fields.keys():
            value = user_data.get(field)
            if value is None or value == '':
                missing_fields[field].append(firebase_uid)
                print(f"  ❌ Missing {field}")
            else:
                print(f"  ✅ {field}: {value}")
    
    print("\n" + "=" * 60)
    print("📋 SUMMARY - Missing Fields:")
    print("-" * 40)
    
    for field, uids in missing_fields.items():
        if uids:
            print(f"❌ {field}: {len(uids)} users missing")
            for uid in uids:
                user_name = next((u['data'].get('name', 'Unknown') for u in users_data if u['firebase_uid'] == uid), 'Unknown')
                print(f"   - {user_name} ({uid})")
        else:
            print(f"✅ {field}: All users have this field")
    
    print(f"\n🎯 Total users in Firebase: {len(users_data)}")
    
    # Check for potential data inconsistencies
    print("\n🔍 Potential Data Issues:")
    print("-" * 40)
    
    for user in users_data:
        data = user['data']
        uid = user['firebase_uid']
        name = data.get('name', 'Unknown')
        
        issues = []
        
        # Check for age issues
        age = data.get('age')
        if age is not None:
            if not isinstance(age, int) or age < 18 or age > 100:
                issues.append(f"Invalid age: {age}")
        
        # Check for location issues
        location = data.get('location')
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        
        if location and (latitude is None or longitude is None):
            issues.append("Location object exists but lat/lng missing")
        elif (latitude is not None or longitude is not None) and not location:
            issues.append("Lat/lng exist but no location object")
        
        # Check for gender preference issues
        gender = data.get('gender')
        preferred_gender = data.get('preferredGender')
        
        if gender and preferred_gender:
            valid_genders = ['male', 'female', 'nonBinary', 'other']
            if gender not in valid_genders:
                issues.append(f"Invalid gender: {gender}")
            if preferred_gender not in valid_genders + ['any']:
                issues.append(f"Invalid preferred gender: {preferred_gender}")
        
        if issues:
            print(f"⚠️  {name} ({uid}):")
            for issue in issues:
                print(f"   - {issue}")
    
    print("\nDone.")

if __name__ == "__main__":
    asyncio.run(audit_firebase_data()) 