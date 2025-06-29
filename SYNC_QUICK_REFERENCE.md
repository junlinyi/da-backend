# Sync Service Quick Reference

## Current Firebase UIDs
- **Juan Baek**: `3STFFuaWc9PG7qhdJH0kaP5NY3A2`
- **Lena Huynh**: `ITnBfONkfab6UUCxr2CwXeLdA8A2`
- **Tram Huynh**: `OterrgfaLtOko7P3cKAbtOGHWyt2`
- **Xzander Fancher**: `RisuLaeeL0hcrqdCo5MXzOf47JS2`
- **Andrew Zhan**: `YNvcqEnr9eZjvGyVRMvs4LoeLOw2`
- **Junlin Yi**: `h0gWfJIdx8NSiqXnbcJcGoQ1uXY2`

## Most Common Commands

### 🔄 Sync Your Profile (After Updates)
```bash
curl -X POST "http://localhost:8000/sync/sync/user/3STFFuaWc9PG7qhdJH0kaP5NY3A2"
```

### 🔄 Sync All Users (Initial Setup)
```bash
curl -X POST "http://localhost:8000/sync/sync/all"
```

### ✅ Check If Sync Worked
```bash
curl "http://localhost:8000/sync/sync/validate/3STFFuaWc9PG7qhdJH0kaP5NY3A2"
```

### 📊 Get Field Mapping Info
```bash
curl "http://localhost:8000/sync/sync/fields"
```

## Troubleshooting Flow

### If No Matches Showing:
1. `curl -X POST "http://localhost:8000/sync/sync/all"`
2. `curl "http://localhost:8000/sync/sync/validate/3STFFuaWc9PG7qhdJH0kaP5NY3A2"`
3. If inconsistent: `curl -X POST "http://localhost:8000/sync/sync/user/3STFFuaWc9PG7qhdJH0kaP5NY3A2"`

### If Photos Not Saving:
1. `curl -X POST "http://localhost:8000/sync/sync/user/3STFFuaWc9PG7qhdJH0kaP5NY3A2"`
2. Try updating profile again in iOS app

### If Data Issues Found:
1. `python audit_firebase_data.py`
2. `python fix_firebase_data.py`
3. `curl -X POST "http://localhost:8000/sync/sync/all"`

## Expected Success Response
```json
{
  "success": true,
  "message": "Successfully synced user 3STFFuaWc9PG7qhdJH0kaP5NY3A2",
  "user_id": 123
}
```

## Data Structure Notes
- **Location**: Separate `latitude` and `longitude` fields (not nested object)
- **Age**: All users now have age data
- **Sync**: Background sync every 5 minutes (Firebase → PostgreSQL only) 