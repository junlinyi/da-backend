# Sync Service Documentation

## Overview

The sync service keeps user data synchronized between Firebase Firestore and PostgreSQL databases. This is essential for the dating app because:

- **Firebase**: Stores user profiles, photos, and real-time data
- **PostgreSQL**: Handles complex matchmaking queries and analytics
- **Sync Service**: Ensures both databases have the same user data

## Architecture

### Sync Flow
```
iOS App → Firebase Firestore → Background Sync → PostgreSQL
```

- **One-way sync**: Firebase → PostgreSQL only
- **Background sync**: Automatic every 5 minutes
- **Manual sync**: API endpoints for development and debugging
- **Real-time**: iOS app writes directly to Firebase

### Data Structure
- **Location**: Separate `latitude` and `longitude` fields (not nested object)
- **Age**: Required field for all users
- **Interests**: PostgreSQL ARRAY type
- **Dynamic mapping**: New fields automatically supported

## Quick Start

### 1. Start the Backend Server
```bash
cd ~/GitHub2/da-backend
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Check Sync Status
```bash
# Get field mapping information
curl "http://localhost:8000/sync/sync/fields"

# Validate your user data
curl "http://localhost:8000/sync/sync/validate/YOUR_FIREBASE_UID"
```

### 3. Manual Sync (if needed)
```bash
# Sync your profile from Firebase to PostgreSQL
curl -X POST "http://localhost:8000/sync/sync/user/YOUR_FIREBASE_UID"

# Sync all users
curl -X POST "http://localhost:8000/sync/sync/all"
```

## API Endpoints

### Sync Operations

#### Sync Specific User
```bash
# Sync from Firebase to PostgreSQL
curl -X POST "http://localhost:8000/sync/sync/user/FIREBASE_UID"
```

#### Sync All Users
```bash
# Sync all users between databases
curl -X POST "http://localhost:8000/sync/sync/all"
```

#### Validate Data Consistency
```bash
# Check if a user's data is the same in both databases
curl "http://localhost:8000/sync/sync/validate/FIREBASE_UID"
```

#### Get Sync Information
```bash
# See what fields can be synced
curl "http://localhost:8000/sync/sync/fields"
```

## Field Mapping

The sync service uses dynamic field mapping that automatically handles new fields:

| Firebase Field | PostgreSQL Field | Type | Required |
|----------------|------------------|------|----------|
| `id` | `firebase_uid` | string | ✅ |
| `email` | `email` | string | ✅ |
| `name` | `name` | string | ❌ |
| `age` | `age` | integer | ❌ |
| `gender` | `gender` | enum | ❌ |
| `interests` | `interests` | array | ❌ |
| `latitude` | `latitude` | float | ❌ |
| `longitude` | `longitude` | float | ❌ |
| `preferredGender` | `preferred_gender` | enum | ❌ |
| `minAgePreference` | `min_age_preference` | integer | ❌ |
| `maxAgePreference` | `max_age_preference` | integer | ❌ |
| `profileImageURL` | `profile_image_url` | string | ❌ |
| `isVerified` | `is_verified` | boolean | ❌ |
| `strikes` | `strikes` | integer | ❌ |
| `maxDistanceKm` | `max_distance_km` | integer | ❌ |

### Location Data Structure
- **Firebase**: Separate `latitude` and `longitude` fields
- **PostgreSQL**: Separate `latitude` and `longitude` columns
- **Legacy**: Old nested `location` object has been removed

## Troubleshooting

### Common Issues

#### "User not found in PostgreSQL"
```bash
# Sync the user from Firebase
curl -X POST "http://localhost:8000/sync/sync/user/FIREBASE_UID"
```

#### "Validation failed"
```bash
# Check what's wrong
curl "http://localhost:8000/sync/sync/validate/FIREBASE_UID"

# Fix data issues
python fix_firebase_data.py
```

#### "Missing age field"
```bash
# All users should have age data
python audit_firebase_data.py
python fix_firebase_data.py
```

### Debugging Flow

1. **Check sync status**:
   ```bash
   curl "http://localhost:8000/sync/sync/fields"
   ```

2. **Validate specific user**:
   ```bash
   curl "http://localhost:8000/sync/sync/validate/FIREBASE_UID"
   ```

3. **Manual sync if needed**:
   ```bash
   curl -X POST "http://localhost:8000/sync/sync/user/FIREBASE_UID"
   ```

4. **Audit data quality**:
   ```bash
   python audit_firebase_data.py
   ```

5. **Fix data issues**:
   ```bash
   python fix_firebase_data.py
   ```

## Background Sync Service

### Automatic Sync
- **Frequency**: Every 5 minutes
- **Scope**: All users, matches, conversations, messages
- **Direction**: Firebase → PostgreSQL only
- **Error Handling**: Logs errors, continues with other operations

### What Gets Synced
1. **User Profiles**: All profile data and preferences
2. **Matches**: Firebase matches → PostgreSQL conversations
3. **Messages**: Message data for analytics
4. **Activity**: User activity timestamps

### Monitoring
- **Logs**: Check application logs for sync status
- **Health**: Background service starts with FastAPI app
- **Errors**: Failed syncs are logged but don't stop the service

## Data Validation

### Validation Rules
- **Age**: 18-120 years
- **Gender**: male, female, nonBinary, other
- **Location**: Valid latitude/longitude coordinates
- **Interests**: Array of strings, max 10 items
- **Bio**: Max 500 characters
- **Name**: Letters, spaces, hyphens, apostrophes only

### Validation Endpoints
```bash
# Validate specific user
curl "http://localhost:8000/sync/sync/validate/FIREBASE_UID"

# Get validation field info
curl "http://localhost:8000/sync/sync/fields"
```

## Expected Responses

### Successful Sync
```json
{
  "success": true,
  "message": "Successfully synced user FIREBASE_UID",
  "user_id": 123
}
```

### Validation Result
```json
{
  "consistent": true,
  "errors": [],
  "db_user_id": 123,
  "firebase_uid": "FIREBASE_UID",
  "validation_passed": true
}
```

### Sync All Results
```json
{
  "success": true,
  "results": {
    "total_users": 6,
    "synced_to_postgres": 6,
    "validation_errors": [],
    "sync_errors": []
  }
}
```

## Development

### Adding New Fields
1. Add to PostgreSQL model (`app/models.py`)
2. Create migration (`alembic revision --autogenerate`)
3. Update field mapping (`app/utils.py`)
4. Add validation rules (`app/utils.py`)
5. Test sync in both directions

### Testing Sync
```bash
# Test specific user
curl -X POST "http://localhost:8000/sync/sync/user/TEST_UID"
curl "http://localhost:8000/sync/sync/validate/TEST_UID"

# Test all users
curl -X POST "http://localhost:8000/sync/sync/all"
```

### Debugging
- **Logs**: Check application logs for detailed error messages
- **Field Mapping**: Use `/sync/fields` endpoint to verify mappings
- **Data Audit**: Use `audit_firebase_data.py` to check data quality
- **Manual Fix**: Use `fix_firebase_data.py` to repair data issues 