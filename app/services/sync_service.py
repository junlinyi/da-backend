# app/services/sync_service.py

import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models import User as DBUser
from app.schemas import UserResponse
from app.utils import (
    db_user_to_api_response, 
    api_response_to_db_user, 
    validate_user_data_consistency,
    validate_user_data_comprehensive,
    validate_sync_data_integrity,
    sanitize_user_data,
    log_sync_validation_result,
    validate_firebase_uid,
    validate_email_format,
    # New dynamic functions
    db_user_to_api_response_dynamic,
    api_response_to_db_user_dynamic,
    firestore_to_db_user_dynamic,
    get_supported_fields,
    validate_field_compatibility
)
import firebase_admin
from firebase_admin import firestore
from firebase_admin import auth

logger = logging.getLogger(__name__)

class DataSyncService:
    """Service to synchronize data from Firebase Firestore to PostgreSQL (one-way sync)"""
    
    def __init__(self, db: Session):
        self.db = db
        self.firestore_db = firestore.client()
    
    def sync_user_from_firebase_to_db(self, firebase_uid: str) -> Optional[DBUser]:
        """Sync user data from Firebase Firestore to PostgreSQL database"""
        try:
            # Validate Firebase UID format
            uid_valid, uid_error = validate_firebase_uid(firebase_uid)
            if not uid_valid:
                logger.error(f"Invalid Firebase UID format: {uid_error}")
                return None
            
            # Get user data from Firestore
            firestore_doc = self.firestore_db.collection('users').document(firebase_uid).get()
            if not firestore_doc.exists:
                logger.warning(f"User {firebase_uid} not found in Firestore")
                return None
            
            firestore_data = firestore_doc.to_dict()
            
            # Handle missing email field by fetching from Firebase Auth
            if 'email' not in firestore_data or not firestore_data['email']:
                try:
                    # Import Firebase Auth to get user email
                    user_record = auth.get_user(firebase_uid)
                    firestore_data['email'] = user_record.email
                    logger.info(f"Fetched email {user_record.email} from Firebase Auth for user {firebase_uid}")
                except Exception as e:
                    logger.error(f"Failed to fetch email from Firebase Auth for user {firebase_uid}: {str(e)}")
                    return None
            
            # Sanitize the data
            firestore_data = sanitize_user_data(firestore_data)
            
            # Ensure max_distance_km is present and valid
            if 'max_distance_km' not in firestore_data or not isinstance(firestore_data['max_distance_km'], (int, float)):
                firestore_data['max_distance_km'] = 32  # Default to 20 miles
            
            # Validate the data comprehensively
            is_valid, validation_errors = validate_user_data_comprehensive(firestore_data)
            if not is_valid:
                logger.error(f"Validation failed for user {firebase_uid}: {validation_errors}")
                log_sync_validation_result(firebase_uid, False, validation_errors, "firebase_to_db")
                return None
            
            # Get or create user in PostgreSQL
            db_user = self.db.query(DBUser).filter(DBUser.firebase_uid == firebase_uid).first()
            if not db_user:
                # Create new user
                db_user = DBUser(
                    firebase_uid=firebase_uid,
                    email=firestore_data.get('email', ''),
                    is_verified=firestore_data.get('isVerified', False),
                    strikes=firestore_data.get('strikes', 0)
                )
                self.db.add(db_user)
            
            # Validate data integrity before update
            integrity_valid, integrity_errors = validate_sync_data_integrity(db_user, firestore_data)
            if not integrity_valid:
                logger.warning(f"Data integrity issues for user {firebase_uid}: {integrity_errors}")
                log_sync_validation_result(firebase_uid, False, integrity_errors, "firebase_to_db_integrity")
            
            # Update user data from Firestore using dynamic mapping
            self._update_db_user_from_firestore_dynamic(db_user, firestore_data)
            
            self.db.commit()
            logger.info(f"Successfully synced user {firebase_uid} from Firebase to PostgreSQL")
            log_sync_validation_result(firebase_uid, True, [], "firebase_to_db")
            return db_user
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error syncing user {firebase_uid} from Firebase: {str(e)}")
            return None
    
    def validate_user_consistency(self, firebase_uid: str) -> Dict[str, Any]:
        """Validate that user data is consistent between Firebase and PostgreSQL"""
        try:
            # Validate Firebase UID format
            uid_valid, uid_error = validate_firebase_uid(firebase_uid)
            if not uid_valid:
                return {"consistent": False, "errors": [f"Invalid Firebase UID: {uid_error}"]}
            
            # Get user from PostgreSQL
            db_user = self.db.query(DBUser).filter(DBUser.firebase_uid == firebase_uid).first()
            if not db_user:
                return {"consistent": False, "errors": ["User not found in PostgreSQL"]}
            
            # Get user from Firestore
            firestore_doc = self.firestore_db.collection('users').document(firebase_uid).get()
            if not firestore_doc.exists:
                return {"consistent": False, "errors": ["User not found in Firebase"]}
            
            firestore_data = firestore_doc.to_dict()
            
            # Validate Firestore data
            is_valid, validation_errors = validate_user_data_comprehensive(firestore_data)
            if not is_valid:
                return {"consistent": False, "errors": validation_errors}
            
            # Convert database user to API response format for comparison
            api_user = db_user_to_api_response_dynamic(db_user)
            
            # Validate consistency
            errors = validate_user_data_consistency(db_user, api_user)
            
            # Additional integrity checks
            integrity_valid, integrity_errors = validate_sync_data_integrity(db_user, firestore_data)
            if not integrity_valid:
                errors.extend(integrity_errors)
            
            return {
                "consistent": len(errors) == 0,
                "errors": errors,
                "db_user_id": db_user.id,
                "firebase_uid": firebase_uid,
                "validation_passed": is_valid
            }
            
        except Exception as e:
            logger.error(f"Error validating user {firebase_uid}: {str(e)}")
            return {"consistent": False, "errors": [f"Validation error: {str(e)}"]}
    
    def _update_db_user_from_firestore_dynamic(self, db_user: DBUser, firestore_data: Dict[str, Any]):
        """Update PostgreSQL user with data from Firestore using dynamic field mapping"""
        
        # Use dynamic field mapping
        update_data = firestore_to_db_user_dynamic(firestore_data)
        
        # Debug: update data for user
        
        # Apply updates to database user
        for db_field, value in update_data.items():
            # Debug: processing field
            if hasattr(db_user, db_field):
                # Validate field compatibility
                field_valid, field_error = validate_field_compatibility(db_field, value)
                if field_valid:
                    setattr(db_user, db_field, value)
                    # Debug: successfully set field
                else:
                    logger.warning(f"Field validation failed for {db_field}: {field_error}")
                    # Debug: field validation failed
            else:
                logger.warning(f"Database field '{db_field}' not found in User model")
                # Debug: database field not found
    
    def _update_db_user_from_firestore(self, db_user: DBUser, firestore_data: Dict[str, Any]):
        """Legacy method - kept for backward compatibility"""
        self._update_db_user_from_firestore_dynamic(db_user, firestore_data)
    
    def get_sync_field_info(self) -> Dict[str, Any]:
        """Get information about all fields that can be synced"""
        return {
            "supported_fields": get_supported_fields(),
            "field_mapping": {
                "api_to_db": get_db_user_field_mapping(),
                "db_to_api": get_api_to_db_field_mapping()
            },
            "sync_directions": {
                "firebase_to_db": "Firebase Firestore → PostgreSQL (one-way sync only)"
            }
        }
    
    def sync_all_users_from_firebase(self) -> Dict[str, Any]:
        """Sync all users from Firebase to PostgreSQL (one-way sync)"""
        try:
            # Get all users from Firebase
            firestore_users = self.firestore_db.collection('users').stream()
            
            results = {
                "total_firebase_users": 0,
                "synced_to_postgres": 0,
                "validation_errors": [],
                "sync_errors": []
            }
            
            for firestore_doc in firestore_users:
                try:
                    firebase_uid = firestore_doc.id
                    firestore_data = firestore_doc.to_dict()
                    
                    results["total_firebase_users"] += 1
                    
                    # Validate user data before sync
                    is_valid, validation_errors = validate_user_data_comprehensive(firestore_data)
                    if not is_valid:
                        results["validation_errors"].append({
                            "user_id": firebase_uid,
                            "errors": validation_errors
                        })
                        continue
                    
                    # Sync to PostgreSQL
                    if self.sync_user_from_firebase_to_db(firebase_uid):
                        results["synced_to_postgres"] += 1
                    else:
                        results["sync_errors"].append(f"Failed to sync user {firebase_uid} to PostgreSQL")
                        
                except Exception as e:
                    results["sync_errors"].append(f"Error syncing user {firebase_uid}: {str(e)}")
            
            logger.info(f"Sync completed: {results}")
            return results
            
        except Exception as e:
            logger.error(f"Error in sync_all_users_from_firebase: {str(e)}")
            return {"error": str(e)}
    
    def validate_all_users(self) -> Dict[str, Any]:
        """Validate all users for data consistency and integrity"""
        try:
            # Get all users from PostgreSQL
            db_users = self.db.query(DBUser).all()
            
            results = {
                "total_users": len(db_users),
                "consistent_users": 0,
                "inconsistent_users": 0,
                "validation_details": []
            }
            
            for db_user in db_users:
                try:
                    consistency_result = self.validate_user_consistency(db_user.firebase_uid)
                    
                    if consistency_result["consistent"]:
                        results["consistent_users"] += 1
                    else:
                        results["inconsistent_users"] += 1
                    
                    results["validation_details"].append({
                        "user_id": db_user.firebase_uid,
                        "consistent": consistency_result["consistent"],
                        "errors": consistency_result.get("errors", [])
                    })
                    
                except Exception as e:
                    results["validation_details"].append({
                        "user_id": db_user.firebase_uid,
                        "consistent": False,
                        "errors": [f"Validation error: {str(e)}"]
                    })
                    results["inconsistent_users"] += 1
            
            logger.info(f"Validation completed: {results}")
            return results
            
        except Exception as e:
            logger.error(f"Error in validate_all_users: {str(e)}")
            return {"error": str(e)} 