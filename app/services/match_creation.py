# app/services/match_creation.py

from firebase_admin import firestore
from datetime import datetime
from typing import Optional

def create_match_in_firestore(
    user1_uid: str, 
    user2_uid: str, 
    match_score: Optional[float] = None,
    status: str = "pending"
) -> str:
    """
    Create a new match in Firestore with enhanced metadata.
    
    Args:
        user1_uid: First user's UID
        user2_uid: Second user's UID
        match_score: Optional match score (0-1)
        status: Match status (pending, accepted, rejected)
    
    Returns:
        str: The ID of the created match document
    """
    db = firestore.client()
    match_ref = db.collection("matches").document()
    
    # Create match data with enhanced metadata
    match_data = {
        "users": [user1_uid, user2_uid],
        "lastMessage": "",
        "lastUpdated": firestore.SERVER_TIMESTAMP,
        "status": status,
        "matchScore": match_score,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "lastInteraction": firestore.SERVER_TIMESTAMP,
        "metadata": {
            "user1LastActive": firestore.SERVER_TIMESTAMP,
            "user2LastActive": firestore.SERVER_TIMESTAMP,
            "user1UnreadCount": 0,
            "user2UnreadCount": 0,
            "user1Status": "active",  # active, inactive, blocked
            "user2Status": "active"
        }
    }
    
    match_ref.set(match_data)
    print(f"Match created in Firestore: {match_ref.id}")
    return match_ref.id

def update_match_status(match_id: str, status: str) -> bool:
    """
    Update the status of an existing match.
    
    Args:
        match_id: The ID of the match document
        status: New status (pending, accepted, rejected)
    
    Returns:
        bool: True if update was successful
    """
    try:
        db = firestore.client()
        match_ref = db.collection("matches").document(match_id)
        
        match_ref.update({
            "status": status,
            "lastUpdated": firestore.SERVER_TIMESTAMP
        })
        return True
    except Exception as e:
        print(f"Error updating match status: {e}")
        return False

def update_user_activity(match_id: str, user_uid: str) -> bool:
    """
    Update the last active timestamp for a user in a match.
    
    Args:
        match_id: The ID of the match document
        user_uid: The UID of the user to update
    
    Returns:
        bool: True if update was successful
    """
    try:
        db = firestore.client()
        match_ref = db.collection("matches").document(match_id)
        
        # Determine which user to update
        user_field = "user1LastActive" if match_ref.get().to_dict()["users"][0] == user_uid else "user2LastActive"
        
        match_ref.update({
            f"metadata.{user_field}": firestore.SERVER_TIMESTAMP,
            "lastInteraction": firestore.SERVER_TIMESTAMP
        })
        return True
    except Exception as e:
        print(f"Error updating user activity: {e}")
        return False
