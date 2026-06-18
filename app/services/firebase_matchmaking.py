# app/services/firebase_matchmaking.py

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Dict, Any, Optional
from geopy.distance import geodesic
import firebase_admin
from firebase_admin import firestore
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models import User, Swipe, Conversation
from app.dependencies import verify_firebase_token

logger = logging.getLogger(__name__)

class FirebaseMatchmakingService:
    """
    Real-time matchmaking service using Firebase for live data
    """
    
    def __init__(self):
        self.firestore_db = firestore.client()
        
    async def get_potential_matches_realtime(
        self, 
        user_firebase_uid: str, 
        db: AsyncSession,
        max_results: int = 7
    ) -> Dict[str, Any]:
        """
        Get potential matches using real-time Firebase data
        """
        try:
            # Get current user from PostgreSQL (for preferences and validation)
            result = await db.execute(select(User).where(User.firebase_uid == user_firebase_uid))
            current_user = result.scalars().first()
            
            if not current_user:
                raise ValueError("User not found")
            
            # Get real-time data from Firebase
            firebase_users = await self._get_firebase_users()
            firebase_matches = await self._get_firebase_matches()
            firebase_swipes = await self._get_firebase_swipes()
            
            # Get today's swipes from PostgreSQL (for consistency)
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            swipes_result = await db.execute(
                select(Swipe)
                .where(Swipe.swiper_id == current_user.id)
                .where(Swipe.timestamp >= today)
            )
            today_swipes = swipes_result.scalars().all()
            swiped_ids = {swipe.swiped_id for swipe in today_swipes}
            
            # Get users who are already matched (from Firebase for real-time)
            matched_user_ids = self._get_matched_user_ids(user_firebase_uid, firebase_matches)
            
            # Filter and score potential matches
            potential_matches = []
            for firebase_user in firebase_users:
                # Skip if it's the current user
                if firebase_user['firebase_uid'] == user_firebase_uid:
                    continue
                    
                # Get PostgreSQL user data for detailed filtering
                pg_user = await self._get_postgres_user(firebase_user['firebase_uid'], db)
                if not pg_user:
                    continue
                
                # Skip if already swiped today
                if pg_user.id in swiped_ids:
                    continue
                    
                # Skip if already matched
                if pg_user.firebase_uid in matched_user_ids:
                    continue
                
                # Apply filtering criteria
                if not self._meets_basic_criteria(current_user, pg_user):
                    continue
                
                # Calculate match score
                match_score = self._calculate_match_score(current_user, pg_user)
                
                if match_score >= 0.3:  # Minimum score threshold
                    potential_matches.append({
                        'user': pg_user,
                        'score': match_score,
                        'firebase_data': firebase_user
                    })
            
            # Sort by score and take top results
            potential_matches.sort(key=lambda x: x['score'], reverse=True)
            top_matches = potential_matches[:max_results]
            
            # Format response
            matches_data = []
            for match in top_matches:
                user = match['user']
                matches_data.append({
                    "id": user.firebase_uid,
                    "name": user.name or "",
                    "age": user.age,
                    "bio": user.bio or "",
                    "gender": user.gender,
                    "interests": user.interests or [],
                    "profileImageUrl": user.profile_image_url,
                    "location": {
                        "latitude": user.latitude,
                        "longitude": user.longitude,
                        "city": user.location if user.location else None,
                        "state": user.state
                    } if user.latitude and user.longitude else None,
                    "matchScore": match['score']
                })
            
            remaining_swipes = max(0, max_results - len(today_swipes))
            
            return {
                "matches": matches_data,
                "remainingSwipes": remaining_swipes
            }
            
        except Exception:
            raise
    
    async def _get_firebase_users(self) -> List[Dict[str, Any]]:
        """Get all users from Firebase"""
        try:
            users_ref = self.firestore_db.collection('users')
            users = []
            for user_doc in users_ref.stream():
                user_data = user_doc.to_dict()
                user_data['firebase_uid'] = user_doc.id
                users.append(user_data)
            return users
        except Exception as e:
            logger.error(f"Error getting Firebase users: {e}")
            return []
    
    async def _get_firebase_matches(self) -> List[Dict[str, Any]]:
        """Get all matches from Firebase"""
        try:
            matches_ref = self.firestore_db.collection('matches')
            matches = []
            for match_doc in matches_ref.stream():
                match_data = match_doc.to_dict()
                match_data['match_id'] = match_doc.id
                matches.append(match_data)
            return matches
        except Exception as e:
            logger.error(f"Error getting Firebase matches: {e}")
            return []
    
    async def _get_firebase_swipes(self) -> List[Dict[str, Any]]:
        """Get recent swipes from Firebase (if available)"""
        try:
            # This would depend on your Firebase structure
            # For now, we'll use PostgreSQL swipes
            return []
        except Exception as e:
            logger.error(f"Error getting Firebase swipes: {e}")
            return []
    
    def _get_matched_user_ids(self, user_firebase_uid: str, firebase_matches: List[Dict[str, Any]]) -> set:
        """Get set of Firebase UIDs that the user is already matched with"""
        matched_ids = set()
        for match in firebase_matches:
            users = match.get('users', [])
            if user_firebase_uid in users and len(users) == 2:
                # Add the other user to matched set
                other_user = next(uid for uid in users if uid != user_firebase_uid)
                matched_ids.add(other_user)
        return matched_ids
    
    async def _get_postgres_user(self, firebase_uid: str, db: AsyncSession) -> Optional[User]:
        """Get PostgreSQL user by Firebase UID"""
        try:
            result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
            return result.scalars().first()
        except Exception as e:
            logger.error(f"Error getting PostgreSQL user: {e}")
            return None
    
    def _meets_basic_criteria(self, current_user: User, potential_match: User) -> bool:
        """Check if potential match meets basic criteria"""
        # Gender preference
        if current_user.preferred_gender not in [potential_match.gender, "any"]:
            return False
        
        # Age preference — skip check if either bound or the match's age is unset
        if current_user.min_age_preference is not None and current_user.max_age_preference is not None:
            if potential_match.age is None:
                return False
            if not (current_user.min_age_preference <= potential_match.age <= current_user.max_age_preference):
                return False
        
        # Must have complete profile
        if not all([potential_match.name, potential_match.age, potential_match.gender,
                   potential_match.latitude, potential_match.longitude]):
            return False
        
        # Distance check
        if current_user.latitude and current_user.longitude and potential_match.latitude and potential_match.longitude:
            distance = geodesic(
                (current_user.latitude, current_user.longitude),
                (potential_match.latitude, potential_match.longitude)
            ).kilometers
            
            max_distance = current_user.max_distance_km or 32
            if distance > max_distance:
                return False
        
        return True
    
    def _calculate_match_score(self, user1: User, user2: User) -> float:
        """Calculate match score between two users"""
        score = 0.0

        # Age compatibility (closer ages score higher). Age derives from birthdate;
        # skip the age component if either user has no birthdate set yet.
        if user1.age is not None and user2.age is not None:
            age_diff = abs(user1.age - user2.age)
            age_score = max(0, 1 - (age_diff / 20))  # 20 years difference = 0 score
            score += age_score * 0.3  # 30% weight
        
        # Location proximity
        if user1.latitude and user1.longitude and user2.latitude and user2.longitude:
            distance = geodesic(
                (user1.latitude, user1.longitude),
                (user2.latitude, user2.longitude)
            ).kilometers
            location_score = max(0, 1 - (distance / 100))  # 100km = 0 score
            score += location_score * 0.4  # 40% weight
        
        # Common interests
        if user1.interests and user2.interests:
            common_interests = len(set(user1.interests) & set(user2.interests))
            interest_score = min(1, common_interests / 5)  # 5 common interests = max score
            score += interest_score * 0.3  # 30% weight
        
        return round(score, 2) 