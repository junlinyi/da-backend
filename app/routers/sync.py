# app/routers/sync.py
"""
Sync Router - Synchronize data from Firebase Firestore to PostgreSQL (one-way sync)

This router provides endpoints to keep user data synchronized from Firebase Firestore
to PostgreSQL database. This is essential for the dating app because:
- Firebase stores user profiles and real-time data (source of truth)
- PostgreSQL handles complex matchmaking queries and analytics
- Data flows one-way: Firebase → PostgreSQL to keep production data clean

USAGE EXAMPLES:

1. Sync a specific user from Firebase to PostgreSQL:
   curl -X POST "http://localhost:8000/sync/sync/user/{firebase_uid}"

2. Sync all users from Firebase to PostgreSQL:
   curl -X POST "http://localhost:8000/sync/sync/all"

3. Validate user data consistency:
   curl "http://localhost:8000/sync/sync/validate/{firebase_uid}"

4. Get information about syncable fields:
   curl "http://localhost:8000/sync/sync/fields"

DETAILED USAGE:

# Sync your user profile from Firebase to PostgreSQL
curl -X POST "http://localhost:8000/sync/sync/user/Bas3uWN0XKNgU8lB7R93iZ2wiup1"

# Sync all users from Firebase to PostgreSQL (useful for initial setup or bulk sync)
curl -X POST "http://localhost:8000/sync/sync/all"

# Check if your user data is consistent between databases
curl "http://localhost:8000/sync/sync/validate/Bas3uWN0XKNgU8lB7R93iZ2wiup1"

# See what fields can be synced
curl "http://localhost:8000/sync/sync/fields"

WHEN TO USE:

- After creating a new profile in the iOS app
- After updating profile information in the iOS app
- When you notice missing matches (indicates sync issues)
- During development to ensure data consistency
- Before running matchmaking algorithms

TROUBLESHOOTING:

If you're not seeing matches:
1. First run: curl -X POST "http://localhost:8000/sync/sync/all"
2. Check consistency: curl "http://localhost:8000/sync/sync/validate/{your_firebase_uid}"
3. If inconsistent, sync your specific user: curl -X POST "http://localhost:8000/sync/sync/user/{your_firebase_uid}"

NOTE: This is a one-way sync system. Data flows from Firebase (source) to PostgreSQL (destination).
Test users created directly in PostgreSQL will not appear in the iOS app.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db_sync
from app.services.sync_service import DataSyncService
from app.dependencies import verify_firebase_token
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models import User
import firebase_admin
from firebase_admin import firestore
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/sync/user/{firebase_uid}")
async def sync_user_from_firebase(
    firebase_uid: str,
    decoded_token=Depends(verify_firebase_token),
    db: Session = Depends(get_db_sync)
):
    """
    Sync a specific user from Firebase to PostgreSQL
    
    This endpoint copies user data from Firebase Firestore to PostgreSQL.
    Use this when you've updated your profile in the iOS app and want
    the changes to be available for matchmaking.
    
    Args:
        firebase_uid: The Firebase UID of the user to sync
        
    Returns:
        Success message with user ID if sync was successful
        
    Example:
        curl -X POST "http://localhost:8000/sync/sync/user/Bas3uWN0XKNgU8lB7R93iZ2wiup1"
    """
    try:
        sync_service = DataSyncService(db)
        user = sync_service.sync_user_from_firebase_to_db(firebase_uid)
        
        if user:
            return {
                "success": True,
                "message": f"Successfully synced user {firebase_uid}",
                "user_id": user.id
            }
        else:
            raise HTTPException(status_code=404, detail=f"Failed to sync user {firebase_uid}")
            
    except Exception as e:
        logger.error(f"Error syncing user {firebase_uid}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")

@router.post("/sync/all")
async def sync_all_users_from_firebase(decoded_token=Depends(verify_firebase_token), db: Session = Depends(get_db_sync)):
    """
    Sync all users from Firebase to PostgreSQL
    
    This endpoint synchronizes all users from Firebase Firestore to PostgreSQL.
    Use this for initial setup or when you want to ensure all
    user data from Firebase is available in PostgreSQL for matchmaking.
    
    Returns:
        Summary of sync results including counts and any errors
        
    Example:
        curl -X POST "http://localhost:8000/sync/sync/all"
    """
    try:
        sync_service = DataSyncService(db)
        results = sync_service.sync_all_users_from_firebase()
        
        return {
            "success": True,
            "results": results
        }
        
    except Exception as e:
        logger.error(f"Error syncing all users from Firebase: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")

@router.get("/sync/validate/{firebase_uid}")
async def validate_user_consistency(
    firebase_uid: str,
    decoded_token=Depends(verify_firebase_token),
    db: Session = Depends(get_db_sync)
):
    """
    Validate that a user's data is consistent between Firebase and PostgreSQL
    
    This endpoint checks if a user's data is the same in both databases.
    Use this to diagnose sync issues or verify that data is consistent.
    
    Args:
        firebase_uid: The Firebase UID of the user to validate
        
    Returns:
        Validation results including consistency status and any errors
        
    Example:
        curl "http://localhost:8000/sync/sync/validate/Bas3uWN0XKNgU8lB7R93iZ2wiup1"
    """
    try:
        sync_service = DataSyncService(db)
        result = sync_service.validate_user_consistency(firebase_uid)
        
        return result
        
    except Exception as e:
        logger.error(f"Error validating user {firebase_uid}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Validation failed: {str(e)}")

@router.get("/sync/fields")
async def get_sync_field_info(decoded_token=Depends(verify_firebase_token), db: Session = Depends(get_db_sync)):
    """
    Get information about fields that can be synced
    
    This endpoint returns information about which user fields can be
    synchronized from Firebase to PostgreSQL, including field mappings
    and sync directions.
    
    Returns:
        Information about syncable fields and their mappings
        
    Example:
        curl "http://localhost:8000/sync/sync/fields"
    """
    try:
        sync_service = DataSyncService(db)
        return sync_service.get_sync_field_info()
        
    except Exception as e:
        logger.error(f"Error getting sync field info: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get field info: {str(e)}")

@router.post("/users")
async def sync_users(
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Manual sync of users from Firebase to PostgreSQL
    Note: This is now also handled automatically by the background sync service
    """
    try:
        # Initialize Firebase
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        
        firestore_db = firestore.client()
        
        # Get all users from Firebase
        users_ref = firestore_db.collection('users')
        firebase_users = users_ref.stream()
        
        synced_count = 0
        for user_doc in firebase_users:
            user_data = user_doc.to_dict()
            firebase_uid = user_doc.id
            
            # Check if user already exists
            result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
            existing_user = result.scalar_one_or_none()
            
            if not existing_user:
                # Create new user — accept either email or phone_number from Firestore;
                # phone-only users have no email and vice versa.
                new_user = User(
                    firebase_uid=firebase_uid,
                    email=user_data.get('email') or None,
                    phone_number=user_data.get('phone_number') or user_data.get('phoneNumber') or None,
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
                synced_count += 1
                logger.info(f"Created user: {user_data.get('name', 'Unknown')} ({firebase_uid})")
        
        await db.commit()
        
        return {
            "message": f"Successfully synced {synced_count} new users from Firebase to PostgreSQL",
            "synced_count": synced_count
        }
        
    except Exception as e:
        logger.error(f"Error syncing users: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to sync users: {str(e)}")

@router.post("/all")
async def sync_all(
    decoded_token=Depends(verify_firebase_token)
):
    """
    Manual sync of all data from Firebase to PostgreSQL
    This triggers the same operations as the background sync service
    """
    try:
        from app.services.firebase_sync_service import sync_service
        
        # Trigger all sync operations
        await sync_service.sync_users()
        await sync_service.sync_matches_to_conversations()
        await sync_service.sync_messages()
        await sync_service.sync_user_activity()
        
        return {
            "message": "Successfully synced all data from Firebase to PostgreSQL",
            "synced": ["users", "matches", "messages", "user_activity"]
        }
        
    except Exception as e:
        logger.error(f"Error in manual sync: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to sync data: {str(e)}")

@router.get("/status")
async def sync_status(decoded_token=Depends(verify_firebase_token)):
    """
    Get the status of the background sync service
    """
    try:
        from app.services.firebase_sync_service import sync_service
        
        return {
            "background_sync_running": sync_service.is_running,
            "message": "Background sync service runs automatically every 30 seconds"
        }
        
    except Exception as e:
        logger.error(f"Error getting sync status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get sync status: {str(e)}") 