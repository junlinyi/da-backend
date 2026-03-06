# app/services/firebase_sync_service.py

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import firebase_admin
from firebase_admin import credentials, firestore
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import SessionLocal
from app.models import User, Conversation, Message, Match

# Initialize Firebase if not already initialized
try:
    firebase_admin.get_app()
except ValueError:
    try:
        cred = credentials.Certificate("facedate-6616e-ebf102022977.json")
        firebase_admin.initialize_app(cred)
    except Exception as e:
        logging.error(f"Failed to initialize Firebase: {e}")

logger = logging.getLogger(__name__)

async def get_db_session():
    """Get a database session for background services"""
    async with SessionLocal() as session:
        yield session

class FirebaseSyncService:
    """
    Background service to sync data from Firebase to PostgreSQL for analytics and training.
    This runs independently and doesn't affect the real-time user experience.
    """
    
    def __init__(self):
        self.firestore_db = firestore.client()
        self.is_running = False
        
    async def start_sync(self):
        """Start the background sync service"""
        if self.is_running:
            logger.warning("Sync service is already running")
            return
            
        self.is_running = True
        logger.info("Starting Firebase to PostgreSQL sync service")
        
        try:
            while self.is_running:
                await self.sync_users()
                await self.sync_matches_to_conversations()
                await self.sync_messages()
                await self.sync_user_activity()
                
                # Wait 5 minutes before next sync (reduced from 30 seconds for cost efficiency)
                await asyncio.sleep(300)
                
        except Exception as e:
            logger.error(f"Sync service error: {e}")
            self.is_running = False
            
    async def stop_sync(self):
        """Stop the background sync service"""
        self.is_running = False
        logger.info("Stopping Firebase to PostgreSQL sync service")
        
    async def sync_users(self):
        """Sync users from Firebase to PostgreSQL"""
        async for db in get_db_session():
            try:
                # Get all users from Firebase
                users_ref = self.firestore_db.collection('users')
                firebase_users = users_ref.stream()
                
                for user_doc in firebase_users:
                    user_data = user_doc.to_dict()
                    firebase_uid = user_doc.id
                    
                    # Check if user already exists in PostgreSQL
                    existing_user = await self.get_user_by_firebase_uid(firebase_uid, db)
                    
                    if not existing_user:
                        # Create new user in PostgreSQL
                        new_user = User(
                            firebase_uid=firebase_uid,
                            email=user_data.get('email', ''),
                            name=user_data.get('name'),
                            age=user_data.get('age'),
                            gender=user_data.get('gender'),
                            preferred_gender=user_data.get('preferredGender'),
                            min_age_preference=user_data.get('minAgePreference', 18),
                            max_age_preference=user_data.get('maxAgePreference', 120),
                            max_distance_km=user_data.get('maxDistanceKm', 32),
                            latitude=user_data.get('latitude'),
                            longitude=user_data.get('longitude'),
                            location=None if isinstance(user_data.get('location'), dict) else user_data.get('location'),
                            state=user_data.get('state'),
                            interests=user_data.get('interests', []),
                            bio=user_data.get('bio'),
                            profile_image_url=user_data.get('profileImageURL'),
                            additional_image_urls=user_data.get('additionalImageURLs', []),
                            profile_completed=user_data.get('profileCompleted', False)
                        )
                        db.add(new_user)
                        logger.info(f"Created new user in PostgreSQL: {user_data.get('name', 'Unknown')} ({firebase_uid})")
                    else:
                        # Update existing user with latest data from Firebase
                        existing_user.name = user_data.get('name', existing_user.name)
                        existing_user.email = user_data.get('email', existing_user.email)
                        existing_user.age = user_data.get('age', existing_user.age)
                        existing_user.gender = user_data.get('gender', existing_user.gender)
                        existing_user.preferred_gender = user_data.get('preferredGender', existing_user.preferred_gender)
                        existing_user.min_age_preference = user_data.get('minAgePreference', existing_user.min_age_preference)
                        existing_user.max_age_preference = user_data.get('maxAgePreference', existing_user.max_age_preference)
                        existing_user.max_distance_km = user_data.get('maxDistanceKm', existing_user.max_distance_km)
                        existing_user.latitude = user_data.get('latitude', existing_user.latitude)
                        existing_user.longitude = user_data.get('longitude', existing_user.longitude)
                        
                        # Handle location field - Firebase may send dict or string
                        location_data = user_data.get('location', existing_user.location)
                        if isinstance(location_data, dict):
                            # Skip updating location if it's a dict (incompatible with VARCHAR field)
                            pass
                        else:
                            existing_user.location = location_data
                        existing_user.state = user_data.get('state', existing_user.state)
                        existing_user.interests = user_data.get('interests', existing_user.interests)
                        existing_user.bio = user_data.get('bio', existing_user.bio)
                        existing_user.profile_image_url = user_data.get('profileImageURL', existing_user.profile_image_url)
                        existing_user.additional_image_urls = user_data.get('additionalImageURLs', existing_user.additional_image_urls)
                        existing_user.profile_completed = user_data.get('profileCompleted', existing_user.profile_completed)
                        
                        logger.info(f"Updated user in PostgreSQL: {existing_user.name} ({firebase_uid})")
                
                await db.commit()
                
            except Exception as e:
                logger.error(f"Error syncing users: {e}")
                await db.rollback()
                break
            
    async def sync_matches_to_conversations(self):
        """Sync Firebase matches to PostgreSQL conversations and matches tables"""
        async for db in get_db_session():
            try:
                # Get all matches from Firebase
                matches_ref = self.firestore_db.collection('matches')
                firebase_matches = matches_ref.stream()
                
                for match_doc in firebase_matches:
                    match_data = match_doc.to_dict()
                    match_id = match_doc.id
                    
                    users = match_data.get('users', [])
                    if len(users) != 2:
                        continue
                        
                    user1_uid, user2_uid = users[0], users[1]
                    
                    # Get user IDs from Firebase UIDs
                    user1 = await self.get_user_by_firebase_uid(user1_uid, db)
                    user2 = await self.get_user_by_firebase_uid(user2_uid, db)
                    
                    if not user1 or not user2:
                        logger.warning(f"Could not find users for match {match_id}")
                        continue
                    
                    # Always store matches as (min_id, max_id)
                    min_id = min(user1.id, user2.id)
                    max_id = max(user1.id, user2.id)
                    
                    # Parse lastUpdated field robustly
                    last_updated = match_data.get('lastUpdated')
                    if isinstance(last_updated, datetime):
                        last_message_at = last_updated
                    elif isinstance(last_updated, (int, float)):
                        last_message_at = datetime.fromtimestamp(last_updated / 1000)
                    else:
                        last_message_at = None
                    
                    # Check if conversation already exists
                    existing_conv = await db.execute(
                        select(Conversation).where(
                            ((Conversation.user1_id == min_id) & (Conversation.user2_id == max_id)) |
                            ((Conversation.user1_id == max_id) & (Conversation.user2_id == min_id))
                        )
                    )
                    existing = existing_conv.scalar_one_or_none()
                    
                    if not existing:
                        # Create new conversation
                        conversation = Conversation(
                            user1_id=min_id,
                            user2_id=max_id,
                            last_message=match_data.get('lastMessage'),
                            last_message_at=last_message_at
                        )
                        db.add(conversation)
                        logger.info(f"Created conversation for match {match_id}: {user1.name} ↔ {user2.name}")
                    else:
                        # Update existing conversation
                        existing.last_message = match_data.get('lastMessage')
                        if last_message_at:
                            existing.last_message_at = last_message_at
                        logger.info(f"Updated conversation for match {match_id}: {user1.name} ↔ {user2.name}")
                    
                    # Also sync to matches table for analytics
                    # Check if match already exists in matches table (min_id, max_id)
                    existing_match = await db.execute(
                        select(Match).where(
                            (Match.user_id == min_id) & (Match.matched_user_id == max_id)
                        )
                    )
                    existing_match_obj = existing_match.scalar_one_or_none()
                    
                    if not existing_match_obj:
                        # Create new match record
                        # Calculate a simple match score based on common interests
                        match_score = 0.5  # Default score
                        if user1.interests and user2.interests:
                            common_interests = len(set(user1.interests) & set(user2.interests))
                            match_score = min(1.0, common_interests / 3.0)  # Max score for 3+ common interests
                        
                        match_record = Match(
                            user_id=min_id,
                            matched_user_id=max_id,
                            match_score=match_score,
                            status='pending',  # Default status
                            created_at=match_data.get('createdAt', datetime.now(timezone.utc))
                        )
                        db.add(match_record)
                        logger.info(f"Created match record for analytics: {user1.name} ↔ {user2.name} (score: {match_score:.2f})")
                    else:
                        # Update existing match record if needed
                        # Could update status, match_score, etc. based on Firebase data
                        logger.info(f"Match record already exists for analytics: {user1.name} ↔ {user2.name}")
                    
                await db.commit()
                
            except Exception as e:
                logger.error(f"Error syncing matches: {e}")
                await db.rollback()
                break
            
    async def sync_messages(self):
        """Sync Firebase messages to PostgreSQL"""
        async for db in get_db_session():
            try:
                # Get all conversations from Firebase (new structure)
                conversations_ref = self.firestore_db.collection('conversations')
                conversations = conversations_ref.stream()
                
                for conversation in conversations:
                    conversation_id = conversation.id
                    conversation_data = conversation.to_dict()
                    participants = conversation_data.get('participants', [])
                    
                    if len(participants) != 2:
                        continue
                        
                    user1_uid, user2_uid = participants[0], participants[1]
                    
                    # Get user IDs from Firebase UIDs
                    user1 = await self.get_user_by_firebase_uid(user1_uid, db)
                    user2 = await self.get_user_by_firebase_uid(user2_uid, db)
                    
                    if not user1 or not user2:
                        continue
                    
                    # Get conversation ID from PostgreSQL
                    conv_result = await db.execute(
                        select(Conversation).where(
                            ((Conversation.user1_id == user1.id) & (Conversation.user2_id == user2.id)) |
                            ((Conversation.user1_id == user2.id) & (Conversation.user2_id == user1.id))
                        )
                    )
                    pg_conversation = conv_result.scalar_one_or_none()
                    
                    if not pg_conversation:
                        continue
                    
                    # Get messages from Firebase conversations collection
                    messages_ref = conversation.reference.collection('messages')
                    firebase_messages = messages_ref.stream()
                    
                    for msg_doc in firebase_messages:
                        msg_data = msg_doc.to_dict()
                        msg_id = msg_doc.id
                        
                        # Check if message already exists
                        existing_msg = await db.execute(
                            select(Message).where(Message.firebase_id == msg_id)
                        )
                        existing = existing_msg.scalar_one_or_none()
                        
                        if not existing:
                            sender_uid = msg_data.get('senderId')
                            
                            # Skip system messages for PostgreSQL sync
                            if sender_uid == 'system':
                                continue
                                
                            sender = await self.get_user_by_firebase_uid(sender_uid, db)
                            
                            if sender:
                                message = Message(
                                    conversation_id=pg_conversation.id,
                                    sender_id=sender.id,
                                    content=msg_data.get('content', ''),
                                    message_type=msg_data.get('messageType', 'text'),
                                    timestamp=msg_data.get('timestamp'),
                                    firebase_id=msg_id
                                )
                                db.add(message)
                                logger.info(f"Synced message to PostgreSQL: {msg_data.get('content', '')[:50]}...")
                
                await db.commit()
                
            except Exception as e:
                logger.error(f"Error syncing messages: {e}")
                await db.rollback()
                break
            
    async def sync_user_activity(self):
        """Sync user activity data from Firebase to PostgreSQL"""
        async for db in get_db_session():
            try:
                # Get all users from Firebase
                users_ref = self.firestore_db.collection('users')
                firebase_users = users_ref.stream()
                
                for user_doc in firebase_users:
                    user_data = user_doc.to_dict()
                    firebase_uid = user_doc.id
                    
                    user = await self.get_user_by_firebase_uid(firebase_uid, db)
                    if user:
                        # Update last active timestamp
                        last_active = user_data.get('lastActive')
                        if last_active:
                            if isinstance(last_active, datetime):
                                user.last_active = last_active
                            elif isinstance(last_active, (int, float)):
                                user.last_active = datetime.fromtimestamp(last_active / 1000)
                
                await db.commit()
                
            except Exception as e:
                logger.error(f"Error syncing user activity: {e}")
                await db.rollback()
                break
            
    async def get_user_by_firebase_uid(self, firebase_uid: str, db: AsyncSession) -> Optional[User]:
        """Get PostgreSQL user by Firebase UID"""
        result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
        return result.scalar_one_or_none()

# Global sync service instance
sync_service = FirebaseSyncService()

async def start_background_sync():
    """Start the background sync service"""
    await sync_service.start_sync()

async def stop_background_sync():
    """Stop the background sync service"""
    await sync_service.stop_sync() 