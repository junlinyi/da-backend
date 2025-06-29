#!/usr/bin/env python3
"""
Script to inspect Firestore data for a specific user
"""

import firebase_admin
from firebase_admin import credentials, firestore
import os

# Initialize Firebase
cred = credentials.Certificate(os.path.expanduser('~/GitHub2/da-backend/facedate-6616e-ebf102022977.json'))
firebase_admin.initialize_app(cred)

def inspect_user(firebase_uid):
    """Inspect the Firestore document for a specific user"""
    
    db = firestore.client()
    doc_ref = db.collection('users').document(firebase_uid)
    doc = doc_ref.get()
    
    if not doc.exists:
        print(f"User {firebase_uid} not found in Firestore")
        return
    
    data = doc.to_dict()
    print(f"Firestore document for user {firebase_uid}:")
    print("=" * 50)
    
    for key, value in data.items():
        print(f"{key}: {value} (type: {type(value).__name__})")
    
    print("\n" + "=" * 50)
    print("Location analysis:")
    
    # Check for location data in different formats
    if 'location' in data:
        print(f"Found 'location' field: {data['location']}")
    if 'latitude' in data:
        print(f"Found 'latitude' field: {data['latitude']}")
    if 'longitude' in data:
        print(f"Found 'longitude' field: {data['longitude']}")
    
    # Check for age data
    if 'age' in data:
        print(f"Found 'age' field: {data['age']}")
    if 'birthday' in data:
        print(f"Found 'birthday' field: {data['birthday']}")
    
    # Check for gender preferences
    if 'preferredGender' in data:
        print(f"Found 'preferredGender' field: {data['preferredGender']}")

if __name__ == "__main__":
    # Inspect the user we're having issues with
    inspect_user("OterrgfaLtOko7P3cKAbtOGHWyt2") 