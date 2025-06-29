#!/usr/bin/env python3
"""
Script to clean up duplicate match documents in Firebase.
This script finds matches with the same users and keeps only one per user pair.
"""

import firebase_admin
from firebase_admin import credentials, firestore
import sys
import os

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

def cleanup_duplicate_matches():
    """Clean up duplicate match documents in Firebase."""
    
    # Initialize Firebase
    cred = credentials.Certificate("facedate-6616e-ebf102022977.json")
    try:
        firebase_admin.initialize_app(cred)
    except ValueError:
        # App already initialized
        pass
    
    db = firestore.client()
    matches_ref = db.collection("matches")
    
    print("🔍 Scanning for duplicate matches...")
    
    # Get all matches
    all_matches = matches_ref.stream()
    match_groups = {}
    
    # Group matches by user pairs
    for match_doc in all_matches:
        match_data = match_doc.to_dict()
        users = match_data.get("users", [])
        
        if len(users) == 2:
            # Sort user IDs to ensure consistent grouping regardless of order
            user_pair = tuple(sorted(users))
            if user_pair not in match_groups:
                match_groups[user_pair] = []
            match_groups[user_pair].append({
                'id': match_doc.id,
                'data': match_data,
                'created_at': match_data.get('createdAt')
            })
    
    print(f"📊 Found {len(match_groups)} unique user pairs")
    
    # Find and clean up duplicates
    duplicates_found = 0
    for user_pair, matches in match_groups.items():
        if len(matches) > 1:
            duplicates_found += 1
            print(f"\n🔄 Found {len(matches)} matches for users {user_pair}:")
            
            # Sort by creation time (keep the oldest one)
            matches.sort(key=lambda x: x['created_at'] if x['created_at'] else 0)
            
            # Keep the first (oldest) match, delete the rest
            keep_match = matches[0]
            delete_matches = matches[1:]
            
            print(f"   ✅ Keeping: {keep_match['id']} (created: {keep_match['created_at']})")
            
            for match_to_delete in delete_matches:
                print(f"   🗑️  Deleting: {match_to_delete['id']} (created: {match_to_delete['created_at']})")
                matches_ref.document(match_to_delete['id']).delete()
    
    if duplicates_found == 0:
        print("\n✅ No duplicate matches found!")
    else:
        print(f"\n✅ Cleaned up {duplicates_found} sets of duplicate matches")
    
    # Verify cleanup
    print("\n🔍 Verifying cleanup...")
    all_matches_after = matches_ref.stream()
    match_groups_after = {}
    
    for match_doc in all_matches_after:
        match_data = match_doc.to_dict()
        users = match_data.get("users", [])
        
        if len(users) == 2:
            user_pair = tuple(sorted(users))
            if user_pair not in match_groups_after:
                match_groups_after[user_pair] = []
            match_groups_after[user_pair].append(match_doc.id)
    
    remaining_duplicates = sum(1 for matches in match_groups_after.values() if len(matches) > 1)
    
    if remaining_duplicates == 0:
        print("✅ Verification successful: No duplicate matches remain")
    else:
        print(f"⚠️  Warning: {remaining_duplicates} sets of duplicates still exist")
    
    print(f"\n📈 Final stats:")
    print(f"   - Total unique user pairs: {len(match_groups_after)}")
    print(f"   - Total match documents: {sum(len(matches) for matches in match_groups_after.values())}")

if __name__ == "__main__":
    cleanup_duplicate_matches() 