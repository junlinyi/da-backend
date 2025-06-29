# app/services/validation_service.py

import logging
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timedelta
from app.utils import (
    validate_user_data_comprehensive,
    validate_email_format,
    validate_age,
    validate_name,
    validate_bio,
    validate_interests,
    validate_location,
    validate_age_preferences,
    validate_gender,
    validate_profile_image_url,
    validate_strikes,
    validate_firebase_uid,
    sanitize_user_data
)
from app.schemas import UserResponse, Location, Gender
from app.models import User as DBUser

logger = logging.getLogger(__name__)

class ValidationService:
    """Centralized validation service for the application"""
    
    def __init__(self):
        self.validation_cache = {}  # Simple cache for validation results
    
    def validate_user_registration(self, user_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate user registration data"""
        errors = []
        
        # Required fields for registration
        required_fields = ['email', 'firebase_uid']
        for field in required_fields:
            if field not in user_data or not user_data[field]:
                errors.append(f"{field.replace('_', ' ').title()} is required")
        
        if errors:
            return False, errors
        
        # Validate email format
        email_valid, email_error = validate_email_format(user_data['email'])
        if not email_valid:
            errors.append(email_error)
        
        # Validate Firebase UID
        uid_valid, uid_error = validate_firebase_uid(user_data['firebase_uid'])
        if not uid_valid:
            errors.append(uid_error)
        
        # Sanitize data
        sanitized_data = sanitize_user_data(user_data)
        
        # Comprehensive validation
        is_valid, validation_errors = validate_user_data_comprehensive(sanitized_data)
        if not is_valid:
            errors.extend(validation_errors)
        
        return len(errors) == 0, errors
    
    def validate_profile_update(self, user_data: Dict[str, Any], existing_user: Optional[DBUser] = None) -> Tuple[bool, List[str]]:
        """Validate profile update data"""
        errors = []
        
        # Sanitize data
        sanitized_data = sanitize_user_data(user_data)
        
        # Validate individual fields if present
        if 'name' in sanitized_data:
            name_valid, name_error = validate_name(sanitized_data['name'])
            if not name_valid:
                errors.append(name_error)
        
        if 'bio' in sanitized_data:
            bio_valid, bio_error = validate_bio(sanitized_data['bio'])
            if not bio_valid:
                errors.append(bio_error)
        
        if 'age' in sanitized_data:
            age_valid, age_error = validate_age(sanitized_data['age'])
            if not age_valid:
                errors.append(age_error)
        
        if 'gender' in sanitized_data:
            try:
                gender = Gender(sanitized_data['gender']) if sanitized_data['gender'] else None
                gender_valid, gender_error = validate_gender(gender)
                if not gender_valid:
                    errors.append(gender_error)
            except ValueError:
                errors.append("Invalid gender value")
        
        if 'interests' in sanitized_data:
            interests_valid, interests_error = validate_interests(sanitized_data['interests'])
            if not interests_valid:
                errors.append(interests_error)
        
        if 'location' in sanitized_data and sanitized_data['location']:
            try:
                location = Location(**sanitized_data['location']) if isinstance(sanitized_data['location'], dict) else sanitized_data['location']
                location_valid, location_error = validate_location(location)
                if not location_valid:
                    errors.append(location_error)
            except Exception as e:
                errors.append(f"Invalid location data: {str(e)}")
        
        if 'profileImageURL' in sanitized_data:
            url_valid, url_error = validate_profile_image_url(sanitized_data['profileImageURL'])
            if not url_valid:
                errors.append(url_error)
        
        return len(errors) == 0, errors
    
    def validate_preferences_update(self, preferences_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate preferences update data"""
        errors = []
        
        # Sanitize data
        sanitized_data = sanitize_user_data(preferences_data)
        
        # Validate age preferences
        min_age = sanitized_data.get('minAgePreference')
        max_age = sanitized_data.get('maxAgePreference')
        age_pref_valid, age_pref_error = validate_age_preferences(min_age, max_age)
        if not age_pref_valid:
            errors.append(age_pref_error)
        
        # Validate preferred gender
        if 'preferredGender' in sanitized_data:
            try:
                pref_gender = Gender(sanitized_data['preferredGender']) if sanitized_data['preferredGender'] else None
                pref_gender_valid, pref_gender_error = validate_gender(pref_gender)
                if not pref_gender_valid:
                    errors.append(pref_gender_error)
            except ValueError:
                errors.append("Invalid preferred gender value")
        
        return len(errors) == 0, errors
    
    def validate_swipe_data(self, swipe_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate swipe data"""
        errors = []
        
        # Required fields
        if 'swiped_id' not in swipe_data:
            errors.append("Swiped user ID is required")
        
        if 'liked' not in swipe_data:
            errors.append("Like status is required")
        
        if errors:
            return False, errors
        
        # Validate data types
        if not isinstance(swipe_data['swiped_id'], int):
            errors.append("Swiped user ID must be an integer")
        
        if not isinstance(swipe_data['liked'], bool):
            errors.append("Like status must be a boolean")
        
        # Validate business rules
        if swipe_data['swiped_id'] <= 0:
            errors.append("Invalid swiped user ID")
        
        return len(errors) == 0, errors
    
    def validate_match_data(self, match_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate match data"""
        errors = []
        
        # Required fields
        required_fields = ['user_id', 'matched_user_id']
        for field in required_fields:
            if field not in match_data:
                errors.append(f"{field.replace('_', ' ').title()} is required")
        
        if errors:
            return False, errors
        
        # Validate data types
        if not isinstance(match_data['user_id'], int):
            errors.append("User ID must be an integer")
        
        if not isinstance(match_data['matched_user_id'], int):
            errors.append("Matched user ID must be an integer")
        
        # Validate business rules
        if match_data['user_id'] <= 0:
            errors.append("Invalid user ID")
        
        if match_data['matched_user_id'] <= 0:
            errors.append("Invalid matched user ID")
        
        if match_data['user_id'] == match_data['matched_user_id']:
            errors.append("User cannot match with themselves")
        
        # Validate status if present
        if 'status' in match_data:
            valid_statuses = ['pending', 'accepted', 'rejected']
            if match_data['status'] not in valid_statuses:
                errors.append(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
        
        return len(errors) == 0, errors
    
    def validate_user_activity(self, user_id: str, last_active: datetime) -> Tuple[bool, List[str]]:
        """Validate user activity data"""
        errors = []
        
        # Validate user ID
        uid_valid, uid_error = validate_firebase_uid(user_id)
        if not uid_valid:
            errors.append(uid_error)
        
        # Validate last active timestamp
        if not isinstance(last_active, datetime):
            errors.append("Last active must be a datetime object")
        else:
            # Check if last active is not in the future
            if last_active > datetime.utcnow():
                errors.append("Last active cannot be in the future")
            
            # Check if last active is not too far in the past (e.g., more than 1 year)
            one_year_ago = datetime.utcnow() - timedelta(days=365)
            if last_active < one_year_ago:
                errors.append("Last active seems too far in the past")
        
        return len(errors) == 0, errors
    
    def validate_data_consistency(self, source_data: Dict[str, Any], target_data: Dict[str, Any], 
                                critical_fields: List[str] = None) -> Tuple[bool, List[str]]:
        """Validate data consistency between two sources"""
        errors = []
        
        if critical_fields is None:
            critical_fields = ['email', 'firebase_uid']
        
        for field in critical_fields:
            source_value = source_data.get(field)
            target_value = target_data.get(field)
            
            if source_value != target_value:
                errors.append(f"{field} mismatch: source={source_value}, target={target_value}")
        
        return len(errors) == 0, errors
    
    def validate_security_constraints(self, user_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate security-related constraints"""
        errors = []
        
        # Check for potentially malicious content
        suspicious_patterns = [
            r'<script',  # Script tags
            r'javascript:',  # JavaScript protocol
            r'data:text/html',  # Data URLs
            r'vbscript:',  # VBScript
            r'on\w+\s*=',  # Event handlers
        ]
        
        for key, value in user_data.items():
            if isinstance(value, str):
                for pattern in suspicious_patterns:
                    if re.search(pattern, value, re.IGNORECASE):
                        errors.append(f"Potentially malicious content detected in {key}")
                        break
        
        # Check for excessive data size
        total_size = len(str(user_data))
        if total_size > 10000:  # 10KB limit
            errors.append("Data size exceeds maximum allowed size")
        
        return len(errors) == 0, errors
    
    def validate_business_rules(self, user_data: Dict[str, Any], operation: str) -> Tuple[bool, List[str]]:
        """Validate business-specific rules"""
        errors = []
        
        if operation == "registration":
            # Business rules for registration
            if 'age' in user_data and user_data['age']:
                if user_data['age'] < 18:
                    errors.append("Users must be at least 18 years old to register")
        
        elif operation == "profile_update":
            # Business rules for profile updates
            if 'strikes' in user_data and user_data['strikes'] > 5:
                errors.append("User has too many strikes to update profile")
        
        elif operation == "matching":
            # Business rules for matching
            if 'is_verified' in user_data and not user_data['is_verified']:
                errors.append("User must be verified to participate in matching")
        
        return len(errors) == 0, errors
    
    def get_validation_summary(self, validation_results: List[Tuple[bool, List[str]]]) -> Dict[str, Any]:
        """Generate a summary of validation results"""
        total_validations = len(validation_results)
        passed_validations = sum(1 for is_valid, _ in validation_results if is_valid)
        failed_validations = total_validations - passed_validations
        
        all_errors = []
        for _, errors in validation_results:
            all_errors.extend(errors)
        
        return {
            "total_validations": total_validations,
            "passed_validations": passed_validations,
            "failed_validations": failed_validations,
            "success_rate": passed_validations / total_validations if total_validations > 0 else 0,
            "total_errors": len(all_errors),
            "unique_errors": list(set(all_errors))
        }
    
    def clear_validation_cache(self):
        """Clear the validation cache"""
        self.validation_cache.clear()
        logger.info("Validation cache cleared") 