# app/dependencies.py

from fastapi import Depends, HTTPException, status, Request
from firebase_admin import auth
from app.firebase import firebase_admin

def verify_firebase_token(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    id_token = auth_header.split(" ")[1]
    
    # Test mode: if token starts with "test_", treat it as a Firebase UID
    if id_token.startswith("test_"):
        firebase_uid = id_token[5:]  # Remove "test_" prefix
        return {"uid": firebase_uid, "test_mode": True}
    
    try:
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token  # Contains user info like uid, email, etc.
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token verification failed: {str(e)}")
