#!/usr/bin/env python3
"""
Test script to debug sync issues
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from utils import firestore_to_db_user_dynamic, get_db_user_field_mapping
from services.sync_service import DataSyncService
from database import get_db_sync

def test_field_mapping():
    """Test the field mapping for the problematic user"""
    
    # Sample Firestore data based on what we saw
    firestore_data = {
        'email': 'secretlytram@gmail.com',
        'name': 'Tram Huynh',
        'bio': 'Hi I\'m tram.',
        'gender': 'female',
        'preferredGender': 'male',
        'profileImageURL': 'https://firebasestorage.googleapis.com:443/v0/b/facedate-6616e.appspot.com/o/users%2FOterrgfaLtOko7P3cKAbtOGHWyt2%2Fimages%2F0.jpg?alt=media&token=0630ebe0-3f52-46bc-8684-aa12c0430aed',
        'location': {'latitude': 37.779379, 'longitude': -122.418433},
        'birthday': '2002-08-19 02:54:00+00:00',
        'interests': ['Travel', 'Food'],
        'minAgePreference': 18,
        'maxAgePreference': 30,
        'isVerified': False,
        'strikes': 0
    }
    
    print("Testing field mapping...")
    print("=" * 50)
    
    # Test field mapping
    field_mapping = get_db_user_field_mapping()
    print("Field mapping:")
    for api_field, db_field in field_mapping.items():
        if api_field in firestore_data:
            print(f"  {api_field} -> {db_field}: {firestore_data[api_field]}")
        else:
            print(f"  {api_field} -> {db_field}: NOT FOUND")
    
    print("\n" + "=" * 50)
    print("Testing firestore_to_db_user_dynamic...")
    
    # Test the conversion function
    update_data = firestore_to_db_user_dynamic(firestore_data)
    print("Update data:")
    for field, value in update_data.items():
        print(f"  {field}: {value}")
    
    print("\n" + "=" * 50)
    print("Testing with actual sync service...")
    
    # Test with actual sync service
    db_session = next(get_db_sync())
    sync_service = DataSyncService(db_session)
    
    # Test the sync
    result = sync_service.sync_user_from_firebase_to_db("OterrgfaLtOko7P3cKAbtOGHWyt2")
    
    if result:
        print(f"Sync successful for user ID: {result.id}")
        print(f"  preferred_gender: {result.preferred_gender}")
        print(f"  latitude: {result.latitude}")
        print(f"  longitude: {result.longitude}")
        print(f"  profile_image_url: {result.profile_image_url}")
    else:
        print("Sync failed")

if __name__ == "__main__":
    test_field_mapping() 