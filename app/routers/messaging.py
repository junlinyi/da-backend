from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models import User, Message, Conversation
from app.schemas import MessageCreate, MessageResponse, ConversationResponse
from app.dependencies import verify_firebase_token
from typing import List
from datetime import datetime
import json
import firebase_admin
from firebase_admin import firestore

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
                            last_message_at=data.get('lastMessageTime', datetime.utcnow()),
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
                timestamp=data.get('timestamp', datetime.utcnow()),
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
        
        return {
            "success": True,
            "message_id": message_ref[1].id,
            "content": message.content,
            "timestamp": datetime.utcnow()
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
        print(f"Error marking messages as read: {e}")

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
                timestamp=datetime.utcnow(),
                firebase_id=conversation_id  # Store Firebase conversation ID for reference
            )
            db.add(new_message)
            await db.commit()
            
    except Exception as e:
        print(f"Error creating message in PostgreSQL: {e}")
        # Don't fail the main operation if PostgreSQL sync fails

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