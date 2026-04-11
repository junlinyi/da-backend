# app/services/match_creation.py

from firebase_admin import firestore
from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models import User, Conversation, Match

async def create_match_in_firestore(
    user1_uid: str, 
    user2_uid: str, 
    db: AsyncSession,
    match_score: Optional[float] = None,
    status: str = "pending"
) -> str:
    """
    Create a new match in Firestore and conversation in PostgreSQL.
    Checks for existing matches to prevent duplicates.
    
    Args:
        user1_uid: First user's UID
        user2_uid: Second user's UID
        db: Database session
        match_score: Optional match score (0-1)
        status: Match status (pending, accepted, rejected)
    
    Returns:
        str: The ID of the created match document (or existing one)
    """
    # Create match in Firestore
    db_firestore = firestore.client()
    
    # Check if match already exists (in either direction)
    matches_ref = db_firestore.collection("matches")
    
    # Query for existing matches with these users (in either order)
    existing_matches = matches_ref.where("users", "array_contains", user1_uid).stream()
    
    for match_doc in existing_matches:
        match_data = match_doc.to_dict()
        users = match_data.get("users", [])
        if len(users) == 2 and user2_uid in users:
            # Match already exists in Firestore
            # Create conversation in PostgreSQL if it doesn't exist
            await create_conversation_in_postgres(user1_uid, user2_uid, db)
            return match_doc.id
    
    # No existing match found, create new one
    match_ref = db_firestore.collection("matches").document()
    
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
    # Match created in Firestore
    
    # Create conversation and match in PostgreSQL, return the PostgreSQL match ID
    match_id = await create_conversation_and_match_in_postgres(user1_uid, user2_uid, db)
    
    return match_id

async def create_conversation_and_match_in_postgres(user1_uid: str, user2_uid: str, db: AsyncSession):
    """
    Create a conversation and match record in PostgreSQL for the matched users.
    Returns the PostgreSQL match ID.
    """
    # Get user IDs from Firebase UIDs
    result = await db.execute(select(User).where(User.firebase_uid == user1_uid))
    user1 = result.scalar_one_or_none()
    
    result = await db.execute(select(User).where(User.firebase_uid == user2_uid))
    user2 = result.scalar_one_or_none()
    
    if not user1 or not user2:
        # Could not find users
        return
    
    # Check if conversation already exists (in either direction)
    existing_conversation = await db.execute(
        select(Conversation).where(
            ((Conversation.user1_id == user1.id) & (Conversation.user2_id == user2.id)) |
            ((Conversation.user1_id == user2.id) & (Conversation.user2_id == user1.id))
        )
    )
    existing = existing_conversation.scalar_one_or_none()
    
    if existing:
        # Conversation already exists in PostgreSQL
        # Still need to check/create the match record
        pass
    else:
        # Create conversation
        conversation = Conversation(
            user1_id=user1.id,
            user2_id=user2.id
        )
        
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        # Conversation created in PostgreSQL
    
    # Check if match already exists (in either direction)
    existing_match = await db.execute(
        select(Match).where(
            ((Match.user_id == user1.id) & (Match.matched_user_id == user2.id)) |
            ((Match.user_id == user2.id) & (Match.matched_user_id == user1.id))
        )
    )
    match_record = existing_match.scalar_one_or_none()
    
    if match_record:
        # Match already exists in PostgreSQL
        return match_record.id
    
    # Create match record
    match_record = Match(
        user_id=user1.id,
        matched_user_id=user2.id,
        status="active"
    )
    
    db.add(match_record)
    await db.commit()
    await db.refresh(match_record)
    
    # Match created in PostgreSQL
    return match_record.id

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
        # Error updating match status
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
        # Error updating user activity
        return False
