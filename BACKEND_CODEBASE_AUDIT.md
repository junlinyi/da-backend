# Backend Codebase Audit & Index

## 📋 Overview

This document provides a comprehensive audit and index of the dating app backend codebase. It serves as a reference for understanding the architecture, data flow, and key components.

## 🏗️ Architecture Summary

```
iOS App ↔ Firebase Firestore ↔ Backend (FastAPI + PostgreSQL)
```

### Data Flow
1. **User Registration**: iOS → Firebase → Background Sync → PostgreSQL
2. **Profile Updates**: iOS → Firebase → Background Sync → PostgreSQL  
3. **Matchmaking**: iOS → Backend API → PostgreSQL → Filtered Results
4. **Messaging**: iOS → Firebase (real-time) → Background Sync → PostgreSQL (analytics)

## 📁 File Structure & Purpose

### Core Application Files

#### `app/main.py` (52 lines)
- **Purpose**: FastAPI application entry point
- **Key Features**:
  - Firebase initialization with service account
  - CORS middleware configuration
  - Router registration (auth, users, matchmaking, sync, messaging)
  - Background sync service startup/shutdown
- **Dependencies**: Firebase Admin SDK, FastAPI, CORS middleware

#### `app/database.py` (38 lines)
- **Purpose**: Database connection and session management
- **Key Features**:
  - Async PostgreSQL connection with SQLAlchemy
  - Sync database connection for background services
  - Session factories for both async and sync operations
  - Dependency injection for database sessions
- **Configuration**: Uses `dating_user:securepassword@localhost/dating_app`

#### `app/models.py` (105 lines)
- **Purpose**: SQLAlchemy database models
- **Key Models**:
  - **User**: Profile data, preferences, location, verification status
  - **Match**: Historical match records (for analytics)
  - **Swipe**: User swipe actions and preferences
  - **Conversation**: Chat sessions between matched users
  - **Message**: Individual messages within conversations
- **Notable Fields**:
  - `firebase_uid`: Links to Firebase user documents
  - `latitude/longitude`: Separate fields (not nested location object)
  - `interests`: PostgreSQL ARRAY type
  - `strikes`: User moderation tracking

#### `app/schemas.py` (145 lines)
- **Purpose**: Pydantic request/response models for API validation
- **Key Schemas**:
  - **UserResponse**: Complete user profile for API responses
  - **ProfileUpdate**: iOS app profile updates (separate from preferences)
  - **PreferencesUpdate**: iOS app preference updates
  - **UserUpdate**: Admin/external API updates (not used by iOS)
  - **Location**: Geographic coordinates with city/state
  - **MessageCreate/Response**: Messaging data structures
- **Validation**: Age constraints, gender enums, preference validation

### Services Layer

#### `app/services/sync_service.py` (286 lines)
- **Purpose**: Manual sync operations between Firebase and PostgreSQL
- **Key Methods**:
  - `sync_user_from_firebase_to_db()`: One-way sync from Firebase to PostgreSQL
  - `validate_user_consistency()`: Check data consistency between systems
  - `sync_all_users_from_firebase()`: Bulk sync operation
  - `get_sync_field_info()`: Field mapping and validation info
- **Features**:
  - Dynamic field mapping for automatic field detection
  - Comprehensive data validation
  - Error handling and logging
  - Firebase Auth integration for email retrieval

#### `app/services/firebase_sync_service.py` (345 lines)
- **Purpose**: Background sync service running every 5 minutes
- **Key Methods**:
  - `sync_users()`: Sync user profiles from Firebase to PostgreSQL
  - `sync_matches_to_conversations()`: Convert Firebase matches to PostgreSQL conversations
  - `sync_messages()`: Sync message data for analytics
  - `sync_user_activity()`: Track user activity timestamps
- **Features**:
  - Automatic startup with FastAPI application
  - Handles data structure differences between systems
  - Creates PostgreSQL records for Firebase-only data
  - Error handling and logging

#### `app/services/matchmaking.py` (118 lines)
- **Purpose**: Core matchmaking algorithm using PostgreSQL data
- **Key Methods**:
  - `find_matches()`: Main matching algorithm with filtering
  - `calculate_match_score()`: Compatibility scoring (age, location, interests)
- **Algorithm**:
  - **Age Compatibility**: 30% weight, closer ages score higher
  - **Location Proximity**: 40% weight, closer distance scores higher
  - **Common Interests**: 30% weight, more common interests score higher
  - **Filtering**: Excludes incomplete profiles, already matched users, today's swipes

#### `app/services/firebase_matchmaking.py` (240 lines)
- **Purpose**: Real-time matchmaking using Firebase data (primary method)
- **Features**:
  - Uses Firebase Firestore for real-time data access
  - Fallback to PostgreSQL-based matching if Firebase fails
  - Handles location-based filtering
  - Returns top 7 matches with remaining swipe count

#### `app/services/validation_service.py` (321 lines)
- **Purpose**: Comprehensive data validation for all user inputs
- **Features**:
  - Field-by-field validation with detailed error messages
  - Business rule validation (age preferences, gender constraints)
  - Data type validation and sanitization
  - Integration with sync services

### API Routers

#### `app/routers/users.py` (136 lines)
- **Purpose**: User management endpoints
- **Key Endpoints**:
  - `GET /me`: Get current user profile (creates user if not exists)
  - `GET /firebase/{firebase_uid}`: Get user by Firebase UID (for conversations)
  - `PUT /me/profile`: Update profile during onboarding
  - `PUT /me/preferences`: Update preferences during onboarding
  - `GET/PUT /{user_id}`: Admin endpoints for any user
- **Authentication**: Firebase token verification required

#### `app/routers/matchmaking.py` (176 lines)
- **Purpose**: Matchmaking and swipe functionality
- **Key Endpoints**:
  - `GET /potential-matches`: Get potential matches (uses Firebase service)
  - `POST /swipe`: Record swipe action and check for matches
- **Features**:
  - Automatic match creation when mutual likes occur
  - Swipe tracking and filtering
  - Fallback to PostgreSQL matching if Firebase fails

#### `app/routers/sync.py` (300 lines)
- **Purpose**: Manual sync operations and validation
- **Key Endpoints**:
  - `POST /sync/user/{firebase_uid}`: Sync specific user
  - `POST /sync/all`: Sync all users
  - `GET /sync/validate/{firebase_uid}`: Validate user data consistency
  - `GET /sync/fields`: Get field mapping information
- **Usage**: Development, debugging, and data repair

#### `app/routers/messaging.py` (209 lines)
- **Purpose**: Messaging and conversation management
- **Features**:
  - Conversation listing with other user details
  - Message history retrieval
  - Unread count tracking
  - Firebase integration for real-time messaging

### Utilities

#### `app/utils.py` (678 lines)
- **Purpose**: Core utility functions for data transformation and validation
- **Key Functions**:

**Data Transformation**:
- `db_user_to_api_response()`: Convert DB model to API response
- `api_response_to_db_user()`: Convert API response to DB updates
- `firestore_to_db_user_dynamic()`: Convert Firestore data to DB format

**Dynamic Field Mapping**:
- `get_db_user_field_mapping()`: API field names to DB column names
- `get_supported_fields()`: Field metadata and validation rules
- `validate_field_compatibility()`: Type checking for field values

**Validation Functions**:
- `validate_user_data_comprehensive()`: Complete user data validation
- `validate_email_format()`, `validate_age()`, `validate_name()`: Field-specific validation
- `validate_sync_data_integrity()`: Cross-system data consistency

**Special Features**:
- Birthday to age conversion for Firestore data
- Location data handling (separate lat/lng fields)
- Gender enum validation and conversion
- Interest array validation and sanitization

## 🔄 Data Synchronization

### Sync Architecture
1. **Primary**: Firebase → PostgreSQL (one-way sync)
2. **Background**: Automatic sync every 5 minutes
3. **Manual**: API endpoints for development and debugging
4. **Validation**: Comprehensive consistency checking

### Field Mapping
- **Dynamic**: Automatic field detection and mapping
- **Bidirectional**: API ↔ Database ↔ Firestore
- **Validation**: Type checking and business rule validation
- **Extensible**: New fields automatically supported

### Data Flow
1. **iOS App** creates/updates user in Firebase
2. **Background Sync** detects changes and updates PostgreSQL
3. **Matchmaking** uses PostgreSQL data for algorithms
4. **API Responses** use PostgreSQL data for consistency

## 🎯 Key Features

### Matchmaking Algorithm
- **Scoring**: Age (30%), Location (40%), Interests (30%)
- **Filtering**: Complete profiles only, geographic distance, age preferences
- **Exclusion**: Already matched users, today's swipes
- **Real-time**: Firebase-based with PostgreSQL fallback

### Data Validation
- **Comprehensive**: Field-by-field validation with detailed errors
- **Business Rules**: Age preferences, gender constraints, location requirements
- **Type Safety**: Automatic type checking and conversion
- **Sanitization**: Data cleaning and normalization

### Error Handling
- **Graceful Degradation**: Fallback mechanisms for service failures
- **Detailed Logging**: Comprehensive error tracking and debugging
- **User Feedback**: Clear error messages for API consumers
- **Data Recovery**: Manual sync and repair capabilities

## 🚨 Critical Notes

### Data Structure Changes
- **Location**: Changed from nested `location` object to separate `latitude`/`longitude` fields
- **Age**: All users now have age data (previously missing)
- **Sync**: Background sync automatically handles structure differences

### Authentication
- **Firebase Auth**: All endpoints require valid Firebase tokens
- **User Creation**: Automatic user creation on first API call
- **Token Verification**: Centralized in `app/dependencies.py`

### Performance Considerations
- **Background Sync**: Reduced from 30 seconds to 5 minutes for cost efficiency
- **Database Indexing**: Critical fields indexed for query performance
- **Connection Pooling**: Efficient database connection management
- **Async Operations**: Non-blocking I/O throughout the application

## 🔧 Development Guidelines

### Adding New Fields
1. Add to PostgreSQL model (`app/models.py`)
2. Create database migration (`alembic revision --autogenerate`)
3. Update Pydantic schemas (`app/schemas.py`)
4. Add to field mapping (`app/utils.py` - `get_db_user_field_mapping()`)
5. Add validation rules (`app/utils.py` - `get_supported_fields()`)
6. Test sync in both directions

### Debugging Sync Issues
1. Check field mapping: `GET /sync/fields`
2. Validate specific user: `GET /sync/validate/{firebase_uid}`
3. Manual sync: `POST /sync/user/{firebase_uid}`
4. Check logs for detailed error messages
5. Use audit scripts: `audit_firebase_data.py`, `fix_firebase_data.py`

### Testing
- **Unit Tests**: Individual function testing
- **Integration Tests**: API endpoint testing
- **Sync Tests**: Cross-system data consistency
- **Performance Tests**: Load testing for matchmaking algorithms

## 📊 Monitoring & Maintenance

### Health Checks
- **Database Connectivity**: PostgreSQL connection status
- **Firebase Connectivity**: Firestore access and authentication
- **Sync Status**: Background sync service health
- **API Performance**: Response times and error rates

### Data Quality
- **Consistency Checks**: Regular validation of cross-system data
- **Completeness**: Profile completion tracking
- **Accuracy**: Location and preference validation
- **Integrity**: Foreign key relationships and constraints

### Backup & Recovery
- **PostgreSQL**: Regular database backups
- **Firebase**: Firestore export capabilities
- **Configuration**: Environment variables and secrets management
- **Documentation**: Up-to-date migration and sync guides 