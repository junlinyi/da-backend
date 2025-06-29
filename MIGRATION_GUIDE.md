# Migration Guide: Adding New Fields to User Model

This guide explains how to add new fields to the User model and ensure they sync properly between the frontend (iOS), Firebase Firestore, and backend (PostgreSQL).

## Current Sync Architecture

```
Frontend (iOS) ↔ Firebase Firestore ↔ Backend (PostgreSQL)
```

The sync system uses **dynamic field mapping** which automatically handles new fields without requiring manual code updates.

## Data Structure Notes

### Current Field Structure
- **Location**: Separate `latitude` and `longitude` fields (not nested object)
- **Age**: Required field for all users
- **Interests**: PostgreSQL ARRAY type
- **Dynamic Mapping**: New fields automatically supported

### Removed Legacy Fields
- **Nested Location Object**: Old `location: {latitude, longitude}` structure has been removed
- **Missing Age Data**: All users now have age data from PostgreSQL

## Step-by-Step Process for Adding New Fields

### 1. Add Field to PostgreSQL Database Model

**File**: `app/models.py`

```python
class User(Base):
    __tablename__ = "users"
    
    # ... existing fields ...
    
    # Add your new field
    new_field = Column(String, nullable=True)  # Example
    # or
    new_boolean_field = Column(Boolean, default=False)
    # or
    new_integer_field = Column(Integer, nullable=True)
```

### 2. Create Database Migration

```bash
# Generate migration
alembic revision --autogenerate -m "Add new_field to users table"

# Apply migration
alembic upgrade head
```

### 3. Update Field Mapping (Automatic)

The dynamic field mapping system will automatically detect new fields. However, you can explicitly add them to the mapping:

**File**: `app/utils.py` - `get_db_user_field_mapping()`

```python
def get_db_user_field_mapping() -> Dict[str, str]:
    return {
        # ... existing mappings ...
        'newField': 'new_field',  # Add your new field mapping
    }
```

### 4. Update API Schema (Optional)

**File**: `app/schemas.py`

```python
class UserResponse(BaseModel):
    # ... existing fields ...
    newField: Optional[str] = None  # Add your new field
```

### 5. Update Frontend Model

**File**: `DatingApp/Sources/Core/Models/User.swift`

```swift
struct User: Identifiable, Codable {
    // ... existing fields ...
    var newField: String?  // Add your new field
    
    // Update initializer
    init(id: String, email: String, name: String?, bio: String?, age: Int?, gender: Gender?, interests: [String]?, location: Location?, profileImageURL: String?, isVerified: Bool, strikes: Int, newField: String?) {
        // ... existing assignments ...
        self.newField = newField
    }
    
    // Update Firestore document conversion
    init?(document: DocumentSnapshot) {
        guard let data = document.data() else { return nil }
        // ... existing assignments ...
        self.newField = data["newField"] as? String
    }
    
    // Update toDictionary method
    func toDictionary() -> [String: Any] {
        var dict: [String: Any] = [
            // ... existing fields ...
        ]
        
        if let newField = newField { dict["newField"] = newField }
        
        return dict
    }
    
    // Update toAPIDictionary method
    func toAPIDictionary() -> [String: Any] {
        var dict: [String: Any] = [
            // ... existing fields ...
        ]
        
        if let newField = newField { dict["newField"] = newField }
        
        return dict
    }
}
```

### 6. Update Validation (Optional)

**File**: `app/utils.py` - `get_supported_fields()`

```python
def get_supported_fields() -> Dict[str, Dict[str, Any]]:
    return {
        # ... existing fields ...
        'newField': {'type': 'string', 'required': False, 'description': 'New field description'},
    }
```

## Example: Adding a "Phone Number" Field

### 1. Database Model Update

```python
# app/models.py
class User(Base):
    # ... existing fields ...
    phone_number = Column(String, nullable=True)
```

### 2. Migration

```bash
alembic revision --autogenerate -m "Add phone_number to users table"
alembic upgrade head
```

### 3. Field Mapping (Automatic)

The system will automatically map `phoneNumber` (API) to `phone_number` (DB).

### 4. Frontend Update

```swift
// DatingApp/Sources/Core/Models/User.swift
struct User: Identifiable, Codable {
    // ... existing fields ...
    var phoneNumber: String?
    
    init?(document: DocumentSnapshot) {
        // ... existing code ...
        self.phoneNumber = data["phoneNumber"] as? String
    }
    
    func toDictionary() -> [String: Any] {
        var dict: [String: Any] = [
            // ... existing fields ...
        ]
        if let phoneNumber = phoneNumber { dict["phoneNumber"] = phoneNumber }
        return dict
    }
}
```

### 5. Validation Update

```python
# app/utils.py
def get_supported_fields() -> Dict[str, Dict[str, Any]]:
    return {
        # ... existing fields ...
        'phoneNumber': {'type': 'string', 'required': False, 'description': 'User phone number'},
    }

def validate_phone_number(phone: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Validate phone number format"""
    if phone is None:
        return True, None
    
    # Basic phone validation
    phone_pattern = r'^\+?[\d\s\-\(\)]+$'
    if not re.match(phone_pattern, phone):
        return False, "Invalid phone number format"
    
    return True, None
```

## Testing the Sync

### 1. Test Backend to Firebase Sync

```python
# Test script
from app.services.sync_service import DataSyncService
from app.database import get_db

db = next(get_db())
sync_service = DataSyncService(db)

# Sync a specific user
result = sync_service.sync_user_from_db_to_firebase("user_firebase_uid")
print(f"Sync result: {result}")

# Validate consistency
consistency = sync_service.validate_user_consistency("user_firebase_uid")
print(f"Consistency: {consistency}")
```

### 2. Test Frontend to Firebase Sync

```swift
// In your iOS app
let user = User(/* ... */)
user.phoneNumber = "+1234567890"

// Save to Firebase
db.collection("users").document(user.id!).setData(user.toDictionary())
```

### 3. Test Firebase to Backend Sync

```python
# The sync will automatically pick up the new field
result = sync_service.sync_user_from_firebase_to_db("user_firebase_uid")
```

## Validation and Error Handling

The system includes comprehensive validation:

1. **Field Type Validation**: Ensures data types match expected formats
2. **Business Rule Validation**: Validates business logic constraints
3. **Data Integrity Validation**: Checks consistency between systems
4. **Security Validation**: Prevents malicious content

## Monitoring and Logging

The sync system provides detailed logging:

```python
# Check sync status
sync_info = sync_service.get_sync_field_info()
print(f"Supported fields: {sync_info['supported_fields']}")

# Validate all users
validation_results = sync_service.validate_all_users()
print(f"Validation results: {validation_results}")
```

## Troubleshooting

### Common Issues

1. **Field Not Syncing**: Check if the field is in the mapping
2. **Type Mismatch**: Ensure data types match between systems
3. **Validation Errors**: Check field validation rules
4. **Missing Frontend Updates**: Ensure frontend model is updated

### Debug Commands

```python
# Get field mapping info
sync_service = DataSyncService(db)
field_info = sync_service.get_sync_field_info()
print(field_info)

# Validate specific user
consistency = sync_service.validate_user_consistency("user_id")
print(consistency)
```

### Data Quality Checks

```bash
# Audit Firebase data
python audit_firebase_data.py

# Fix data issues
python fix_firebase_data.py

# Validate sync
curl "http://localhost:8000/sync/sync/validate/USER_FIREBASE_UID"
```

## Best Practices

1. **Always test sync in both directions**
2. **Use proper data types and constraints**
3. **Add validation for new fields**
4. **Update documentation**
5. **Test with existing data**
6. **Monitor sync logs for errors**

## Migration Checklist

- [ ] Add field to PostgreSQL model
- [ ] Create and run database migration
- [ ] Update field mapping (if needed)
- [ ] Update API schema (if needed)
- [ ] Update frontend model
- [ ] Add validation rules
- [ ] Test sync in both directions
- [ ] Validate data consistency
- [ ] Update documentation
- [ ] Monitor production sync

## Current Field Reference

### Required Fields
- `firebase_uid`: Firebase user ID
- `email`: User email address

### Profile Fields
- `name`: User's full name
- `age`: User's age (18-120)
- `gender`: User's gender (male, female, nonBinary, other)
- `bio`: User's biography (max 500 chars)
- `interests`: Array of interests (max 10 items)
- `latitude`, `longitude`: Location coordinates
- `location`: City name
- `state`: State/province
- `profile_image_url`: Profile photo URL
- `additional_image_urls`: Additional photo URLs

### Preference Fields
- `preferred_gender`: Preferred gender for matches
- `min_age_preference`: Minimum age preference (18-120)
- `max_age_preference`: Maximum age preference (18-120)
- `max_distance_km`: Maximum distance for matches

### Status Fields
- `is_verified`: Verification status
- `strikes`: Number of strikes (moderation)
- `profile_completed`: Profile completion status
- `last_active`: Last activity timestamp

This dynamic system ensures that adding new fields is much simpler and less error-prone than the previous hardcoded approach. 