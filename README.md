# Dating App Backend

A FastAPI-based backend for a dating application with PostgreSQL database and Firebase Firestore integration.

## 🏗️ Architecture

```
iOS App ↔ Firebase Firestore ↔ Backend (FastAPI + PostgreSQL)
```

- **iOS App**: User interface and real-time features
- **Firebase Firestore**: User profiles, photos, real-time data, conversations
- **Backend (PostgreSQL)**: Complex matchmaking algorithms, analytics, data processing
- **Sync Service**: Keeps Firebase and PostgreSQL data synchronized

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- PostgreSQL
- Firebase project with Firestore enabled

### Setup

1. **Clone and install dependencies**
   ```bash
   cd da-backend
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Database setup**
   ```bash
   # Start PostgreSQL (if using Docker)
   docker-compose up -d
   
   # Run migrations
   alembic upgrade head
   ```

3. **Firebase configuration**
   - Place `facedate-6616e-ebf102022977.json` in the root directory
   - Update Firebase project settings as needed

4. **Start the server**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

## 📁 Project Structure

```
da-backend/
├── app/                    # Main application code
│   ├── main.py            # FastAPI app entry point
│   ├── models.py          # SQLAlchemy database models
│   ├── schemas.py         # Pydantic request/response models
│   ├── database.py        # Database connection and session management
│   ├── services/          # Business logic services
│   │   ├── sync_service.py    # Firebase ↔ PostgreSQL sync
│   │   ├── matchmaking_service.py  # Matchmaking algorithms
│   │   └── firebase_sync_service.py # Background sync service
│   ├── api/               # API route handlers
│   │   ├── users.py       # User management endpoints
│   │   ├── matches.py     # Matchmaking endpoints
│   │   └── sync.py        # Sync service endpoints
│   └── utils.py           # Utility functions and helpers
├── alembic/               # Database migrations
├── tests/                 # Test files
├── scripts/               # Utility scripts
├── audit_firebase_data.py # Firebase data audit utility
├── fix_firebase_data.py   # Firebase data repair utility
└── requirements.txt       # Python dependencies
```

## 🔄 Data Flow

### User Registration/Update
1. iOS app creates/updates user in Firebase
2. Sync service detects changes and updates PostgreSQL
3. Matchmaking service uses PostgreSQL data for algorithms

### Matchmaking
1. iOS app requests potential matches via API
2. Backend queries PostgreSQL for compatible users
3. Filters out already matched/swiped users
4. Returns filtered results to iOS app

### Messaging
1. iOS app creates conversations in Firebase
2. Sync service creates corresponding PostgreSQL records
3. Messages stored in Firebase for real-time access

## 📚 Documentation

- **[SYNC_DOCUMENTATION.md](SYNC_DOCUMENTATION.md)**: Detailed sync service documentation
- **[SYNC_QUICK_REFERENCE.md](SYNC_QUICK_REFERENCE.md)**: Quick sync commands reference
- **[MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)**: Guide for adding new fields

## 🔧 Key Features

### Sync Service
- **Bidirectional sync** between Firebase and PostgreSQL
- **Automatic field mapping** for new fields
- **Data validation** and consistency checks
- **Background sync** every 30 seconds

### Matchmaking
- **Compatibility scoring** based on preferences
- **Geographic filtering** by distance
- **Age and gender preference** matching
- **Exclusion of matched/swiped users**

### Data Models
- **Users**: Profile information, preferences, photos
- **Conversations**: Chat sessions between matched users
- **Matches**: Historical match records (for analytics)

## 🛠️ Development

### Adding New Fields
See [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) for step-by-step instructions.

### Database Migrations
```bash
# Create new migration
alembic revision --autogenerate -m "Description of changes"

# Apply migrations
alembic upgrade head
```

### Testing
```bash
# Run tests
pytest tests/

# Run specific test
pytest tests/test_matchmaking.py
```

## 🔍 Monitoring & Debugging

### Sync Status
```bash
# Check sync field info
curl "http://localhost:8000/sync/sync/fields"

# Validate user consistency
curl "http://localhost:8000/sync/sync/validate/USER_FIREBASE_UID"
```

### Data Auditing
```bash
# Audit Firebase data
python audit_firebase_data.py

# Fix Firebase data issues
python fix_firebase_data.py
```

## 🚨 Common Issues

### Sync Problems
- **Missing user data**: Run sync for specific user
- **Inconsistent data**: Use validation endpoint to check
- **New fields not syncing**: Check field mapping configuration

### Matchmaking Issues
- **No matches showing**: Ensure user data is synced
- **Wrong matches**: Check preference settings and filters

### Database Issues
- **Migration errors**: Check Alembic logs
- **Connection issues**: Verify PostgreSQL is running

## 📊 API Endpoints

### Users
- `GET /users/` - Get all users
- `POST /users/` - Create user
- `GET /users/{user_id}` - Get specific user
- `PUT /users/{user_id}` - Update user

### Matchmaking
- `GET /matches/potential/{user_id}` - Get potential matches
- `POST /matches/swipe` - Record swipe action

### Sync
- `POST /sync/sync/user/{firebase_uid}` - Sync specific user
- `POST /sync/sync/all` - Sync all users
- `GET /sync/sync/validate/{firebase_uid}` - Validate user data

## 🔐 Security

- **Firebase Authentication** for user identity
- **Input validation** on all endpoints
- **SQL injection protection** via SQLAlchemy ORM
- **CORS configuration** for iOS app access

## 📈 Performance

- **Database indexing** on frequently queried fields
- **Connection pooling** for database efficiency
- **Async operations** for non-blocking I/O
- **Caching** for frequently accessed data

## 🤝 Contributing

1. Follow the existing code structure
2. Add tests for new features
3. Update documentation for API changes
4. Run data audits after schema changes 