from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models import User, Message, Conversation, Match, MatchOutcome
from sqlalchemy import or_
from app.schemas import MessageCreate, MessageResponse, ConversationResponse
from app.dependencies import verify_firebase_token
from app.services import push_notification_service as push
from typing import List
from datetime import datetime, timezone
import json
import logging
import firebase_admin
from firebase_admin import firestore

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/conversations/test")
async def test_conversations_format():
    """
    Test endpoint to verify conversation format
    """
    return {
        "message": "Messaging API is working!",
        "note": "iOS app uses Firebase for real-time messaging. This endpoint is for testing only."
    }


@router.post("/conversations/sync-matches")
async def sync_match_conversations(
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Ensures a Firestore conversation exists for every matched user in PostgreSQL.
    Call this when the Messages tab loads so that manually-created matches (e.g.
    seeded via admin/testing) show up in the conversation list without requiring
    users to go through the swipe flow.
    """
    current_uid = decoded_token["uid"]

    result = await db.execute(select(User).where(User.firebase_uid == current_uid))
    current_user = result.scalar_one_or_none()
    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")

    matches_result = await db.execute(
        select(Match).where(
            (Match.user_id == current_user.id) | (Match.matched_user_id == current_user.id)
        )
    )
    matches = matches_result.scalars().all()

    firestore_db = firestore.client()
    synced = []

    for match in matches:
        other_id = match.matched_user_id if match.user_id == current_user.id else match.user_id
        other_result = await db.execute(select(User).where(User.id == other_id))
        other_user = other_result.scalar_one_or_none()
        if not other_user:
            continue

        uid1 = current_uid
        uid2 = other_user.firebase_uid

        # Check whether a Firestore conversation already exists for these two users
        conversations_ref = firestore_db.collection("conversations")
        existing_stream = conversations_ref.where("participants", "array_contains", uid1).stream()

        conversation_id = None
        for doc in existing_stream:
            data = doc.to_dict()
            if uid2 in data.get("participants", []):
                conversation_id = doc.id
                break

        if conversation_id is None:
            # Create the missing Firestore conversation
            conv_ref = conversations_ref.document()
            conv_ref.set({
                "participants": [uid1, uid2],
                "lastMessage": "",
                "lastMessageTime": firestore.SERVER_TIMESTAMP,
                "unreadCounts": {uid1: 0, uid2: 0},
                "createdAt": firestore.SERVER_TIMESTAMP,
            })
            conversation_id = conv_ref.id
            logger.info(
                f"sync_match_conversations: created Firestore conversation {conversation_id} "
                f"for match {match.id} ({uid1} <-> {uid2})"
            )

        synced.append({
            "match_id": match.id,
            "conversation_id": conversation_id,
            "other_user_firebase_uid": uid2,
            "other_user_name": other_user.name,
        })

    return {"synced": synced, "total": len(synced)}

# Note: The following endpoints are kept for potential future use or analytics:
# - /conversations (GET) - Could be used for admin dashboard
# - /conversations/{id}/messages (GET) - Could be used for message history/analytics
# - /conversations/{id}/messages (POST) - Could be used for backend-initiated messages

@router.get("/conversations")
async def get_conversations(
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all conversations for the current user from Firebase
    Note: This endpoint fetches from Firebase and syncs to PostgreSQL for analytics
    """
    current_user_firebase_uid = decoded_token["uid"]
    
    # Get current user from PostgreSQL
    result = await db.execute(select(User).where(User.firebase_uid == current_user_firebase_uid))
    current_user = result.scalar_one_or_none()
    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    try:
        # Get conversations from Firebase
        firestore_db = firestore.client()
        conversations_ref = firestore_db.collection('conversations')
        
        # Get conversations where current user is a participant
        conversations = []
        async for doc in conversations_ref.stream():
            data = doc.to_dict()
            participants = data.get('participants', [])
            
            if current_user_firebase_uid in participants:
                # Get the other user's ID
                other_user_id = next((uid for uid in participants if uid != current_user_firebase_uid), None)
                if other_user_id:
                    # Get other user's details from PostgreSQL
                    other_user_result = await db.execute(
                        select(User).where(User.firebase_uid == other_user_id)
                    )
                    other_user = other_user_result.scalar_one_or_none()
                    
                    if other_user:
                        conversation_response = ConversationResponse(
                            id=doc.id,
                            other_user_id=other_user_id,
                            other_user_name=other_user.name or "Unknown User",
                            other_user_profile_image=other_user.profile_image_url,
                            last_message=data.get('lastMessage', ''),
                            last_message_at=data.get('lastMessageTime', datetime.now(timezone.utc)),
                            unread_count=data.get('unreadCounts', {}).get(current_user_firebase_uid, 0)
                        )
                        conversations.append(conversation_response)
        
        return conversations
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching conversations: {str(e)}")

@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,  # Changed to string for Firebase document ID
    limit: int = 50,
    offset: int = 0,
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Get messages for a specific conversation from Firebase
    """
    current_user_firebase_uid = decoded_token["uid"]
    
    # Get current user from PostgreSQL
    result = await db.execute(select(User).where(User.firebase_uid == current_user_firebase_uid))
    current_user = result.scalar_one_or_none()
    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    try:
        # Get conversation from Firebase to verify user is participant
        firestore_db = firestore.client()
        conversation_ref = firestore_db.collection('conversations').document(conversation_id)
        conversation_doc = conversation_ref.get()
        
        if not conversation_doc.exists:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        conversation_data = conversation_doc.to_dict()
        participants = conversation_data.get('participants', [])
        
        if current_user_firebase_uid not in participants:
            raise HTTPException(status_code=403, detail="Not a participant in this conversation")
        
        # Get messages from Firebase
        messages_ref = conversation_ref.collection('messages')
        messages_query = messages_ref.order_by('timestamp', direction=firestore.Query.DESCENDING)
        
        if offset > 0:
            messages_query = messages_query.offset(offset)
        
        messages_query = messages_query.limit(limit)
        
        messages = []
        for doc in messages_query.stream():
            data = doc.to_dict()
            message_response = MessageResponse(
                id=doc.id,
                sender_id=data.get('senderId', ''),
                content=data.get('content', ''),
                timestamp=data.get('timestamp', datetime.now(timezone.utc)),
                message_type=data.get('messageType', 'text')
            )
            messages.append(message_response)
        
        # Reverse to get chronological order
        messages.reverse()
        
        # Mark messages as read (update Firebase)
        await mark_messages_as_read_firebase(conversation_id, current_user_firebase_uid)
        
        return messages
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching messages: {str(e)}")

@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,  # Changed to string for Firebase document ID
    message: MessageCreate,
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Send a message in a conversation (Firebase-based)
    Note: This endpoint is mainly for analytics. Real messaging happens in Firebase.
    """
    current_user_firebase_uid = decoded_token["uid"]
    
    # Get current user from PostgreSQL
    result = await db.execute(select(User).where(User.firebase_uid == current_user_firebase_uid))
    current_user = result.scalar_one_or_none()
    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    try:
        # Verify conversation exists and user is participant
        firestore_db = firestore.client()
        conversation_ref = firestore_db.collection('conversations').document(conversation_id)
        conversation_doc = conversation_ref.get()
        
        if not conversation_doc.exists:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        conversation_data = conversation_doc.to_dict()
        participants = conversation_data.get('participants', [])
        
        if current_user_firebase_uid not in participants:
            raise HTTPException(status_code=403, detail="Not a participant in this conversation")
        
        # Create message in Firebase
        message_data = {
            'content': message.content,
            'senderId': current_user_firebase_uid,
            'timestamp': firestore.SERVER_TIMESTAMP,
            'messageType': message.message_type or 'text'
        }
        
        message_ref = conversation_ref.collection('messages').add(message_data)
        
        # Update conversation with last message
        conversation_ref.update({
            'lastMessage': message.content,
            'lastMessageTime': firestore.SERVER_TIMESTAMP
        })
        
        # Also create message in PostgreSQL for analytics
        await create_message_in_postgresql(
            conversation_id,
            current_user.id,
            message.content,
            message.message_type or 'text',
            db
        )

        # D2 — notify the recipient of the new message (best-effort, fire-and-forget)
        try:
            other_uid_for_push = next((uid for uid in participants if uid != current_user_firebase_uid), None)
            if other_uid_for_push:
                push_recipient_q = await db.execute(select(User).where(User.firebase_uid == other_uid_for_push))
                push_recipient = push_recipient_q.scalar_one_or_none()
                if push_recipient:
                    preview = message.content or ""
                    await push.notify_new_message(
                        recipient=push_recipient,
                        sender_name=current_user.name or "Someone",
                        conversation_id=hash(conversation_id) & 0x7FFFFFFF,  # stable int for routing
                        preview=preview,
                    )
        except Exception as exc:
            logger.warning(f"[PUSH] D2 notification failed: {exc}")

        # Update match_outcomes funnel timestamps (best-effort)
        try:
            other_uid = next((uid for uid in participants if uid != current_user_firebase_uid), None)
            if other_uid:
                other_q = await db.execute(select(User).where(User.firebase_uid == other_uid))
                other_user = other_q.scalar_one_or_none()
                if other_user:
                    match_q = await db.execute(
                        select(Match).where(
                            or_(
                                (Match.user_id == current_user.id) & (Match.matched_user_id == other_user.id),
                                (Match.user_id == other_user.id) & (Match.matched_user_id == current_user.id),
                            )
                        )
                    )
                    match = match_q.scalar_one_or_none()
                    if match:
                        outcome_q = await db.execute(
                            select(MatchOutcome).where(MatchOutcome.match_id == match.id)
                        )
                        outcome = outcome_q.scalar_one_or_none()
                        if outcome:
                            now = datetime.now(timezone.utc)
                            if outcome.first_message_at is None:
                                outcome.first_message_at = now
                            elif outcome.reciprocal_msg_at is None:
                                # First message was from the other user; this is the reply
                                sender_is_user1 = (outcome.user1_id == current_user.id)
                                first_sender_is_user1 = (match.user_id == outcome.user1_id)
                                if sender_is_user1 != first_sender_is_user1:
                                    outcome.reciprocal_msg_at = now
                            await db.commit()
        except Exception as exc:
            logger.warning(f"Failed to update match_outcomes funnel on send_message: {exc}")

        return {
            "success": True,
            "message_id": message_ref[1].id,
            "content": message.content,
            "timestamp": datetime.now(timezone.utc)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error sending message: {str(e)}")

async def mark_messages_as_read_firebase(conversation_id: str, user_firebase_uid: str):
    """
    Mark all messages in a conversation as read for a user (Firebase)
    """
    try:
        firestore_db = firestore.client()
        conversation_ref = firestore_db.collection('conversations').document(conversation_id)
        
        # Update unread count for the user
        conversation_ref.update({
            f'unreadCounts.{user_firebase_uid}': 0
        })
        
    except Exception as e:
        # Error marking messages as read
        pass

async def create_message_in_postgresql(
    conversation_id: str, 
    sender_id: int, 
    content: str, 
    message_type: str,
    db: AsyncSession
):
    """
    Create message in PostgreSQL for analytics purposes
    """
    try:
        # Find the PostgreSQL conversation ID
        result = await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        pg_conversation = result.scalar_one_or_none()
        
        if pg_conversation:
            # Create message in PostgreSQL
            new_message = Message(
                conversation_id=pg_conversation.id,
                sender_id=sender_id,
                content=content,
                message_type=message_type,
                timestamp=datetime.now(timezone.utc),
                firebase_id=conversation_id  # Store Firebase conversation ID for reference
            )
            db.add(new_message)
            await db.commit()
            
    except Exception as e:
        # Error creating message in PostgreSQL
        # Don't fail the main operation if PostgreSQL sync fails
        pass

async def mark_messages_as_read(conversation_id: int, user_id: int, db: AsyncSession):
    """
    Mark all messages in a conversation as read for a user (PostgreSQL)
    """
    # Reset unread count for the user
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    
    if conversation:
        if conversation.user1_id == user_id:
            conversation.user1_unread_count = 0
        else:
            conversation.user2_unread_count = 0
        await db.commit() 