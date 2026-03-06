# app/dependencies.py

from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from firebase_admin import auth as firebase_auth
from app.firebase import firebase_admin
from app.database import get_db
from app.models import User
import logging
import traceback
import os

logger = logging.getLogger(__name__)

def verify_firebase_token(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    id_token = auth_header.split(" ")[1]

    # Test mode: only active when TEST_MODE env var is explicitly set to "true"
    # SECURITY: This bypass must NEVER be enabled in production
    if os.getenv("TEST_MODE", "").lower() == "true" and id_token.startswith("test_"):
        firebase_uid = id_token[5:]  # Remove "test_" prefix
        return {"uid": firebase_uid, "test_mode": True}

    try:
        decoded_token = firebase_auth.verify_id_token(id_token)
        return decoded_token  # Contains user info like uid, email, etc.
    except Exception as e:
        logger.error(f"[TOKEN VERIFICATION ERROR] Failed to verify token: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=401, detail=f"Token verification failed: {str(e)}")

# Helper function to get user by Firebase UID, with on-demand creation
async def get_current_user(decoded_token=Depends(verify_firebase_token), db: AsyncSession = Depends(get_db)):
    firebase_uid = decoded_token["uid"]
    try:
        result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
        user = result.scalars().first()
        if not user:
            logger.warning(f"[USER ON-DEMAND] User {firebase_uid} not found in Postgres. Attempting to fetch from Firebase...")
            try:
                fb_user = firebase_auth.get_user(firebase_uid)
                user = User(
                    firebase_uid=firebase_uid,
                    email=fb_user.email,
                    name=fb_user.display_name or None,
                    profile_image_url=fb_user.photo_url or None,
                    is_active=True
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
                logger.info(f"[USER ON-DEMAND] User {firebase_uid} created in Postgres from Firebase.")
            except Exception as e:
                logger.error(f"[USER ON-DEMAND] Failed to fetch/create user {firebase_uid} from Firebase: {e}\n{traceback.format_exc()}")
                raise HTTPException(status_code=404, detail=f"User not found and could not be created: {e}")
        else:
            logger.info(f"[USER FOUND] User {firebase_uid} found in Postgres (ID: {user.id})")
        return user
    except Exception as e:
        logger.error(f"[USER LOOKUP ERROR] Error looking up user {firebase_uid}: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error looking up user: {e}")
