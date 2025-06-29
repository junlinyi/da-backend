#!/usr/bin/env python3
"""
Script to find a user by email in Firebase Firestore
"""

import sys
import os
import firebase_admin
from firebase_admin import credentials

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from services.sync_service import DataSyncService
from database import get_db_sync

cred = credentials.Certificate(os.path.expanduser('~/GitHub2/da-backend/facedate-6616e-ebf102022977.json'))
firebase_admin.initialize_app(cred)

def find_user_by_email(target_email):
    """Find a user by email in Firebase Firestore"""
    
    print(f"Searching for user with email: {target_email}")
    print("=" * 50)
    
    # Get a database session
    db_session = next(get_db_sync())
    
    try:
        # Create sync service which has access to Firebase
        sync_service = DataSyncService(db_session)
        
        # Get all users from Firebase
        firestore_users = sync_service.firestore_db.collection('users').stream()
        
        found = False
        
        for firestore_doc in firestore_users:
            data = firestore_doc.to_dict()
            email = data.get('email')
            
            if email == target_email:
                print(f"✅ FOUND USER:")
                print(f"   Firebase UID: {firestore_doc.id}")
                print(f"   Email: {email}")
                print(f"   Name: {data.get('name', 'Not set')}")
                print(f"   Profile completed: {data.get('profileCompleted', 'Not set')}")
                print(f"   All data: {data}")
                found = True
                break
            elif email and target_email.lower() in email.lower():
                print(f"🔍 PARTIAL MATCH:")
                print(f"   Firebase UID: {firestore_doc.id}")
                print(f"   Email: {email}")
        
        if not found:
            print(f"❌ No user found with email: {target_email}")
            print("\nAll users in Firebase:")
            print("-" * 30)
            for doc in sync_service.firestore_db.collection('users').stream():
                data = doc.to_dict()
                email = data.get('email', 'NO EMAIL')
                print(f"UID: {doc.id} | Email: {email}")
    
    finally:
        db_session.close()

if __name__ == "__main__":
    target_email = "andrew.zhang@gmail.com"
    find_user_by_email(target_email) 