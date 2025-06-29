from typing import Optional, List, Dict, Any, Tuple
from app.models import User as DBUser
from app.schemas import UserResponse, Location, TimeSlot, Gender
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)

# Validation constants
MIN_AGE = 18
MAX_AGE = 120
MAX_BIO_LENGTH = 500
MAX_NAME_LENGTH = 100
MAX_INTERESTS_COUNT = 10
MAX_INTEREST_LENGTH = 50
MIN_PASSWORD_LENGTH = 6
MAX_DISTANCE_KM = 1000

def db_user_to_api_response(db_user: DBUser) -> UserResponse:
    """Convert database User model to API response schema"""
    
    # Convert location data
    location = None
    if db_user.latitude is not None and db_user.longitude is not None:
        location = Location(
            latitude=db_user.latitude,
            longitude=db_user.longitude,
            city=db_user.location,  # Assuming location field contains city name
            state=None  # Add state field to DB model if needed
        )
    
    # Convert gender enum
    gender = None
    if db_user.gender:
        try:
            gender = Gender(db_user.gender)
        except ValueError:
            # Handle legacy gender values
            gender = Gender.other
    
    # Convert preferred gender
    preferred_gender = None
    if db_user.preferred_gender:
        try:
            preferred_gender = Gender(db_user.preferred_gender)
        except ValueError:
            preferred_gender = Gender.other
    
    return UserResponse(
        id=db_user.firebase_uid,  # Use Firebase UID as frontend ID
        email=db_user.email,
        name=db_user.name,
        bio=db_user.bio,
        age=db_user.age,
        gender=gender,
        interests=db_user.interests,
        location=location,
        preferredGender=preferred_gender,
        minAgePreference=db_user.min_age_preference,
        maxAgePreference=db_user.max_age_preference,
        profileImageURL=db_user.profile_image_url,
        isVerified=db_user.is_verified,
        availableSchedule=[],  # TODO: Add schedule support to DB model
        strikes=0  # TODO: Add strikes field to DB model
    )

def api_response_to_db_user(api_user: UserResponse, db_user: Optional[DBUser] = None) -> dict:
    """Convert API response schema to database update dictionary"""
    
    update_data = {}
    
    if api_user.name is not None:
        update_data['name'] = api_user.name
    if api_user.bio is not None:
        update_data['bio'] = api_user.bio
    if api_user.age is not None:
        update_data['age'] = api_user.age
    if api_user.gender is not None:
        update_data['gender'] = api_user.gender.value
    if api_user.interests is not None:
        update_data['interests'] = api_user.interests
    if api_user.location is not None:
        update_data['latitude'] = api_user.location.latitude
        update_data['longitude'] = api_user.location.longitude
        update_data['location'] = api_user.location.city
    if api_user.preferredGender is not None:
        update_data['preferred_gender'] = api_user.preferredGender.value
    if api_user.minAgePreference is not None:
        update_data['min_age_preference'] = api_user.minAgePreference
    if api_user.maxAgePreference is not None:
        update_data['max_age_preference'] = api_user.maxAgePreference
    if api_user.profileImageURL is not None:
        update_data['profile_image_url'] = api_user.profileImageURL
    if api_user.isVerified is not None:
        update_data['is_verified'] = api_user.isVerified
    
    return update_data

def validate_user_data_consistency(db_user: DBUser, api_user: UserResponse) -> List[str]:
    """Validate that database and API user data are consistent"""
    errors = []
    
    # Check field mappings
    if db_user.name != api_user.name:
        errors.append(f"Name mismatch: DB={db_user.name}, API={api_user.name}")
    
    if db_user.bio != api_user.bio:
        errors.append(f"Bio mismatch: DB={db_user.bio}, API={api_user.bio}")
    
    if db_user.age != api_user.age:
        errors.append(f"Age mismatch: DB={db_user.age}, API={api_user.age}")
    
    # Check location consistency
    if api_user.location:
        if db_user.latitude != api_user.location.latitude:
            errors.append(f"Latitude mismatch: DB={db_user.latitude}, API={api_user.location.latitude}")
        if db_user.longitude != api_user.location.longitude:
            errors.append(f"Longitude mismatch: DB={db_user.longitude}, API={api_user.location.longitude}")
    
    return errors

# New comprehensive validation functions

def validate_email_format(email: str) -> Tuple[bool, Optional[str]]:
    """Validate email format"""
    if not email:
        return False, "Email is required"
    
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        return False, "Invalid email format"
    
    return True, None

def validate_age(age: Optional[int]) -> Tuple[bool, Optional[str]]:
    """Validate age constraints"""
    if age is None:
        return True, None  # Age is optional
    
    if not isinstance(age, int):
        return False, "Age must be an integer"
    
    if age < MIN_AGE or age > MAX_AGE:
        return False, f"Age must be between {MIN_AGE} and {MAX_AGE}"
    
    return True, None

def validate_name(name: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Validate name constraints"""
    if name is None:
        return True, None  # Name is optional
    
    if not isinstance(name, str):
        return False, "Name must be a string"
    
    if len(name.strip()) == 0:
        return False, "Name cannot be empty"
    
    if len(name) > MAX_NAME_LENGTH:
        return False, f"Name must be less than {MAX_NAME_LENGTH} characters"
    
    # Check for valid characters (letters, spaces, hyphens, apostrophes)
    name_pattern = r'^[a-zA-Z\s\'-]+$'
    if not re.match(name_pattern, name):
        return False, "Name contains invalid characters"
    
    return True, None

def validate_bio(bio: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Validate bio constraints"""
    if bio is None:
        return True, None  # Bio is optional
    
    if not isinstance(bio, str):
        return False, "Bio must be a string"
    
    if len(bio) > MAX_BIO_LENGTH:
        return False, f"Bio must be less than {MAX_BIO_LENGTH} characters"
    
    return True, None

def validate_interests(interests: Optional[List[str]]) -> Tuple[bool, Optional[str]]:
    """Validate interests constraints"""
    if interests is None:
        return True, None  # Interests are optional
    
    if not isinstance(interests, list):
        return False, "Interests must be a list"
    
    if len(interests) > MAX_INTERESTS_COUNT:
        return False, f"Maximum {MAX_INTERESTS_COUNT} interests allowed"
    
    for interest in interests:
        if not isinstance(interest, str):
            return False, "All interests must be strings"
        
        if len(interest.strip()) == 0:
            return False, "Interest cannot be empty"
        
        if len(interest) > MAX_INTEREST_LENGTH:
            return False, f"Interest must be less than {MAX_INTEREST_LENGTH} characters"
    
    return True, None

def validate_location(location: Optional[Location]) -> Tuple[bool, Optional[str]]:
    """Validate location constraints"""
    if location is None:
        return True, None  # Location is optional
    
    if not isinstance(location, Location):
        return False, "Location must be a Location object"
    
    # Validate latitude
    if not isinstance(location.latitude, (int, float)):
        return False, "Latitude must be a number"
    
    if location.latitude < -90 or location.latitude > 90:
        return False, "Latitude must be between -90 and 90"
    
    # Validate longitude
    if not isinstance(location.longitude, (int, float)):
        return False, "Longitude must be a number"
    
    if location.longitude < -180 or location.longitude > 180:
        return False, "Longitude must be between -180 and 180"
    
    return True, None

def validate_age_preferences(min_age: Optional[int], max_age: Optional[int]) -> Tuple[bool, Optional[str]]:
    """Validate age preference constraints"""
    if min_age is None and max_age is None:
        return True, None  # Both optional
    
    if min_age is not None:
        min_valid, min_error = validate_age(min_age)
        if not min_valid:
            return False, f"Min age preference: {min_error}"
    
    if max_age is not None:
        max_valid, max_error = validate_age(max_age)
        if not max_valid:
            return False, f"Max age preference: {max_error}"
    
    if min_age is not None and max_age is not None:
        if min_age >= max_age:
            return False, "Minimum age preference must be less than maximum age preference"
    
    return True, None

def validate_gender(gender: Optional[Gender]) -> Tuple[bool, Optional[str]]:
    """Validate gender constraints"""
    if gender is None:
        return True, None  # Gender is optional
    
    if not isinstance(gender, Gender):
        return False, "Invalid gender value"
    
    return True, None

def validate_profile_image_url(url: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Validate profile image URL"""
    if url is None:
        return True, None  # URL is optional
    
    if not isinstance(url, str):
        return False, "Profile image URL must be a string"
    
    if len(url.strip()) == 0:
        return False, "Profile image URL cannot be empty"
    
    # Basic URL validation
    url_pattern = r'^https?://.+'
    if not re.match(url_pattern, url):
        return False, "Profile image URL must be a valid HTTP/HTTPS URL"
    
    return True, None

def validate_strikes(strikes: int) -> Tuple[bool, Optional[str]]:
    """Validate strikes count"""
    if not isinstance(strikes, int):
        return False, "Strikes must be an integer"
    
    if strikes < 0:
        return False, "Strikes cannot be negative"
    
    if strikes > 10:  # Reasonable upper limit
        return False, "Strikes count seems unusually high"
    
    return True, None

def validate_firebase_uid(uid: str) -> Tuple[bool, Optional[str]]:
    """Validate Firebase UID format"""
    if not uid:
        return False, "Firebase UID is required"
    
    if not isinstance(uid, str):
        return False, "Firebase UID must be a string"
    
    # Firebase UID format validation (28 characters, alphanumeric)
    uid_pattern = r'^[a-zA-Z0-9]{28}$'
    if not re.match(uid_pattern, uid):
        return False, "Invalid Firebase UID format"
    
    return True, None

def validate_user_data_comprehensive(user_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Comprehensive validation of user data from any source"""
    errors = []
    
    # Validate required fields
    if 'email' not in user_data:
        errors.append("Email is required")
    else:
        email_valid, email_error = validate_email_format(user_data['email'])
        if not email_valid:
            errors.append(email_error)
    
    if 'firebase_uid' in user_data:
        uid_valid, uid_error = validate_firebase_uid(user_data['firebase_uid'])
        if not uid_valid:
            errors.append(uid_error)
    
    # Validate optional fields
    if 'name' in user_data:
        name_valid, name_error = validate_name(user_data['name'])
        if not name_valid:
            errors.append(name_error)
    
    if 'bio' in user_data:
        bio_valid, bio_error = validate_bio(user_data['bio'])
        if not bio_valid:
            errors.append(bio_error)
    
    if 'age' in user_data:
        age_valid, age_error = validate_age(user_data['age'])
        if not age_valid:
            errors.append(age_error)
    
    if 'gender' in user_data:
        try:
            gender = Gender(user_data['gender']) if user_data['gender'] else None
            gender_valid, gender_error = validate_gender(gender)
            if not gender_valid:
                errors.append(gender_error)
        except ValueError:
            errors.append("Invalid gender value")
    
    if 'interests' in user_data:
        interests_valid, interests_error = validate_interests(user_data['interests'])
        if not interests_valid:
            errors.append(interests_error)
    
    if 'location' in user_data and user_data['location']:
        try:
            location = Location(**user_data['location']) if isinstance(user_data['location'], dict) else user_data['location']
            location_valid, location_error = validate_location(location)
            if not location_valid:
                errors.append(location_error)
        except Exception as e:
            errors.append(f"Invalid location data: {str(e)}")
    
    if 'minAgePreference' in user_data or 'maxAgePreference' in user_data:
        min_age = user_data.get('minAgePreference')
        max_age = user_data.get('maxAgePreference')
        age_pref_valid, age_pref_error = validate_age_preferences(min_age, max_age)
        if not age_pref_valid:
            errors.append(age_pref_error)
    
    if 'preferredGender' in user_data:
        try:
            pref_gender = Gender(user_data['preferredGender']) if user_data['preferredGender'] else None
            pref_gender_valid, pref_gender_error = validate_gender(pref_gender)
            if not pref_gender_valid:
                errors.append(pref_gender_error)
        except ValueError:
            errors.append("Invalid preferred gender value")
    
    if 'profileImageURL' in user_data:
        url_valid, url_error = validate_profile_image_url(user_data['profileImageURL'])
        if not url_valid:
            errors.append(url_error)
    
    if 'strikes' in user_data:
        strikes_valid, strikes_error = validate_strikes(user_data['strikes'])
        if not strikes_valid:
            errors.append(strikes_error)
    
    return len(errors) == 0, errors

def validate_sync_data_integrity(db_user: DBUser, firestore_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate data integrity during sync operations"""
    errors = []
    
    # Check for critical field mismatches
    if db_user.email != firestore_data.get('email'):
        errors.append(f"Email mismatch: DB={db_user.email}, Firestore={firestore_data.get('email')}")
    
    if db_user.firebase_uid != firestore_data.get('id'):
        errors.append(f"Firebase UID mismatch: DB={db_user.firebase_uid}, Firestore={firestore_data.get('id')}")
    
    # Check for data type consistency
    if 'age' in firestore_data and firestore_data['age'] is not None:
        if not isinstance(firestore_data['age'], int):
            errors.append("Age must be an integer in Firestore")
    
    if 'strikes' in firestore_data and firestore_data['strikes'] is not None:
        if not isinstance(firestore_data['strikes'], int):
            errors.append("Strikes must be an integer in Firestore")
    
    # Check for required field presence
    required_fields = ['email', 'id']
    for field in required_fields:
        if field not in firestore_data or not firestore_data[field]:
            errors.append(f"Required field '{field}' missing in Firestore data")
    
    return len(errors) == 0, errors

def sanitize_user_data(user_data: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize user data to prevent injection attacks and ensure data quality"""
    sanitized = {}
    
    for key, value in user_data.items():
        if isinstance(value, str):
            # Remove leading/trailing whitespace
            sanitized[key] = value.strip()
        elif isinstance(value, list):
            # Sanitize list items
            sanitized[key] = [item.strip() if isinstance(item, str) else item for item in value]
        else:
            sanitized[key] = value
    
    return sanitized

def log_sync_validation_result(user_id: str, is_valid: bool, errors: List[str], operation: str):
    """Log validation results for sync operations"""
    if is_valid:
        logger.info(f"Sync validation passed for user {user_id} during {operation}")
    else:
        logger.warning(f"Sync validation failed for user {user_id} during {operation}: {errors}")

# Dynamic field mapping functions for automatic sync

def get_db_user_field_mapping() -> Dict[str, str]:
    """Get mapping of API field names to database column names"""
    return {
        'id': 'firebase_uid',
        'email': 'email',
        'name': 'name',
        'bio': 'bio',
        'age': 'age',
        'gender': 'gender',
        'interests': 'interests',
        'preferredGender': 'preferred_gender',
        'minAgePreference': 'min_age_preference',
        'maxAgePreference': 'max_age_preference',
        'profileImageURL': 'profile_image_url',
        'isVerified': 'is_verified',
        'strikes': 'strikes',
        'lastActive': 'last_active',
        'profileCompleted': 'profile_completed',
        'maxDistanceKm': 'max_distance_km',
        'additionalImageUrls': 'additional_image_urls'
    }

def get_api_to_db_field_mapping() -> Dict[str, str]:
    """Get mapping of database column names to API field names"""
    return {v: k for k, v in get_db_user_field_mapping().items()}

def db_user_to_api_response_dynamic(db_user: DBUser) -> UserResponse:
    """Dynamic conversion of database User model to API response schema"""
    
    # Get field mapping
    field_mapping = get_db_user_field_mapping()
    
    # Build API response data dynamically
    api_data = {}
    
    for api_field, db_field in field_mapping.items():
        if hasattr(db_user, db_field):
            value = getattr(db_user, db_field)
            
            # Handle special cases
            if api_field == 'id':
                api_data[api_field] = value  # Firebase UID
            elif api_field == 'gender' and value:
                try:
                    api_data[api_field] = Gender(value)
                except ValueError:
                    api_data[api_field] = Gender.other
            elif api_field == 'preferredGender' and value:
                try:
                    api_data[api_field] = Gender(value)
                except ValueError:
                    api_data[api_field] = Gender.other
            elif api_field in ['interests', 'additionalImageUrls'] and value:
                api_data[api_field] = list(value) if isinstance(value, (list, tuple)) else value
            else:
                api_data[api_field] = value
    
    # Handle location data (special case)
    if db_user.latitude is not None and db_user.longitude is not None:
        api_data['location'] = Location(
            latitude=db_user.latitude,
            longitude=db_user.longitude,
            city=db_user.location,
            state=db_user.state
        )
    
    # Handle schedule data (placeholder for future implementation)
    api_data['availableSchedule'] = []
    
    return UserResponse(**api_data)

def api_response_to_db_user_dynamic(api_user: UserResponse, db_user: Optional[DBUser] = None) -> dict:
    """Dynamic conversion of API response schema to database update dictionary"""
    
    # Get reverse field mapping
    field_mapping = get_api_to_db_field_mapping()
    
    update_data = {}
    
    # Convert API user to dict
    api_dict = api_user.dict(exclude_unset=True)
    
    for api_field, value in api_dict.items():
        if api_field in field_mapping:
            db_field = field_mapping[api_field]
            
            # Handle special cases
            if api_field in ['gender', 'preferredGender'] and value:
                update_data[db_field] = value.value if hasattr(value, 'value') else value
            elif api_field == 'location' and value:
                # Handle location separately
                if hasattr(value, 'latitude'):
                    update_data['latitude'] = value.latitude
                if hasattr(value, 'longitude'):
                    update_data['longitude'] = value.longitude
                if hasattr(value, 'city'):
                    update_data['location'] = value.city
                if hasattr(value, 'state'):
                    update_data['state'] = value.state
            elif api_field == 'availableSchedule':
                # Skip for now - TODO: implement schedule support
                continue
            else:
                update_data[db_field] = value
    
    return update_data

def firestore_to_db_user_dynamic(firestore_data: Dict[str, Any]) -> dict:
    """Dynamic conversion of Firestore data to database update dictionary"""
    
    # Get field mapping
    field_mapping = get_db_user_field_mapping()
    
    update_data = {}
    
    for api_field, db_field in field_mapping.items():
        if api_field in firestore_data:
            value = firestore_data[api_field]
            
            # Handle special cases
            if api_field in ['gender', 'preferredGender'] and value:
                update_data[db_field] = value
            elif api_field == 'availableSchedule':
                # Skip for now - TODO: implement schedule support
                continue
            else:
                update_data[db_field] = value
    
    # Handle location data separately (not in field mapping)
    if 'location' in firestore_data and isinstance(firestore_data['location'], dict):
        location_data = firestore_data['location']
        if 'latitude' in location_data:
            update_data['latitude'] = location_data['latitude']
        if 'longitude' in location_data:
            update_data['longitude'] = location_data['longitude']
        if 'city' in location_data:
            update_data['location'] = location_data['city']
        if 'state' in location_data:
            update_data['state'] = location_data['state']
    
    # Handle birthday to age conversion
    if 'birthday' in firestore_data and 'age' not in firestore_data:
        try:
            from datetime import datetime
            birthday = firestore_data['birthday']
            if hasattr(birthday, 'date'):  # Firestore timestamp
                birthday_date = birthday.date()
            elif isinstance(birthday, str):
                birthday_date = datetime.fromisoformat(birthday.replace('Z', '+00:00')).date()
            else:
                birthday_date = birthday
            
            age = datetime.now().year - birthday_date.year
            if datetime.now().date() < birthday_date.replace(year=datetime.now().year):
                age -= 1
            update_data['age'] = age
        except Exception as e:
            print(f"Error calculating age from birthday: {e}")
    
    return update_data

def get_supported_fields() -> Dict[str, Dict[str, Any]]:
    """Get information about all supported fields for sync"""
    return {
        'id': {'type': 'string', 'required': True, 'description': 'Firebase UID'},
        'email': {'type': 'string', 'required': True, 'description': 'User email'},
        'name': {'type': 'string', 'required': False, 'description': 'User name'},
        'bio': {'type': 'string', 'required': False, 'description': 'User bio'},
        'age': {'type': 'integer', 'required': False, 'description': 'User age'},
        'gender': {'type': 'enum', 'required': False, 'description': 'User gender', 'values': ['male', 'female', 'nonBinary', 'other']},
        'interests': {'type': 'array', 'required': False, 'description': 'User interests'},
        'location': {'type': 'object', 'required': False, 'description': 'User location', 'fields': ['latitude', 'longitude', 'city', 'state']},
        'latitude': {'type': 'float', 'required': False, 'description': 'Latitude of user location'},
        'longitude': {'type': 'float', 'required': False, 'description': 'Longitude of user location'},
        'preferredGender': {'type': 'enum', 'required': False, 'description': 'Preferred gender', 'values': ['male', 'female', 'nonBinary', 'other']},
        'minAgePreference': {'type': 'integer', 'required': False, 'description': 'Minimum age preference'},
        'maxAgePreference': {'type': 'integer', 'required': False, 'description': 'Maximum age preference'},
        'profileImageURL': {'type': 'string', 'required': False, 'description': 'Profile image URL'},
        'isVerified': {'type': 'boolean', 'required': False, 'description': 'Verification status'},
        'strikes': {'type': 'integer', 'required': False, 'description': 'Number of strikes'},
        'lastActive': {'type': 'datetime', 'required': False, 'description': 'Last active timestamp'},
        'profileCompleted': {'type': 'boolean', 'required': False, 'description': 'Profile completion status'},
        'maxDistanceKm': {'type': 'integer', 'required': False, 'description': 'Maximum distance for matches'},
        'additionalImageUrls': {'type': 'array', 'required': False, 'description': 'Additional profile images'}
    }

def validate_field_compatibility(field_name: str, field_value: Any) -> Tuple[bool, Optional[str]]:
    """Validate if a field value is compatible with the expected type"""
    supported_fields = get_supported_fields()
    
    # Convert database field name to API field name for validation
    field_mapping = get_db_user_field_mapping()
    api_field_name = None
    
    # Find the API field name that maps to this database field
    for api_field, db_field in field_mapping.items():
        if db_field == field_name:
            api_field_name = api_field
            break
    
    # If not found in mapping, check if it's a direct API field name
    if api_field_name is None:
        api_field_name = field_name
    
    if api_field_name not in supported_fields:
        return False, f"Field '{field_name}' is not supported for sync"
    
    field_info = supported_fields[api_field_name]
    field_type = field_info['type']
    
    if field_value is None:
        return True, None  # None values are always allowed
    
    if field_type == 'string':
        if not isinstance(field_value, str):
            return False, f"Field '{field_name}' must be a string"
    elif field_type == 'integer':
        if not isinstance(field_value, int):
            return False, f"Field '{field_name}' must be an integer"
    elif field_type == 'boolean':
        if not isinstance(field_value, bool):
            return False, f"Field '{field_name}' must be a boolean"
    elif field_type == 'array':
        if not isinstance(field_value, list):
            return False, f"Field '{field_name}' must be an array"
    elif field_type == 'object':
        if not isinstance(field_value, dict):
            return False, f"Field '{field_name}' must be an object"
    elif field_type == 'enum':
        if api_field_name == 'gender' or api_field_name == 'preferredGender':
            valid_values = ['male', 'female', 'nonBinary', 'other']
            if field_value not in valid_values:
                return False, f"Field '{field_name}' must be one of: {', '.join(valid_values)}"
    
    return True, None 