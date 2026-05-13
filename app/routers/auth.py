# app/routers/auth.py

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import User
from app.schemas import UserCreate, UserResponse
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordRequestForm
from firebase_admin import auth
from app.firebase import firebase_admin
from app.limiter import limiter
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(tags=["Auth"])

async def get_user_by_email(email: str, db: AsyncSession):
    """
    Using email as unique identifier, get the user object.
    """
    result = await db.execute(
        select(User).where(User.email == email)
    )
    return result.scalar_one_or_none()

@router.post("/register", response_model=UserResponse)
@limiter.limit("5/minute")
async def register_user(
    user_data: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new user with Firebase and create a corresponding record in PostgreSQL.

    Supports both email-auth and phone-auth tokens. Token-match assertion branches
    on which claim is present: `email` for email/password sign-ins, `phone_number`
    for SMS OTP sign-ins. Linked accounts can have either or both.
    """
    logger.info(f"Received registration request: email={user_data.email!r} phone={user_data.phone_number!r}")

    # Verify Firebase token
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    id_token = auth_header.split(" ")[1]
    try:
        decoded_token = auth.verify_id_token(id_token)
    except Exception as e:
        logger.error(f"Token verification failed: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Token verification failed: {str(e)}")

    token_email = decoded_token.get("email")
    token_phone = decoded_token.get("phone_number")

    # Branch the request-vs-token-match assertion on which claim the token carries.
    # Email-auth tokens have `email`; phone-auth tokens have `phone_number`.
    if token_email:
        if user_data.email != token_email:
            raise HTTPException(status_code=401, detail="Email mismatch with token")
    elif token_phone:
        if user_data.phone_number != token_phone:
            raise HTTPException(status_code=401, detail="Phone number mismatch with token")
    else:
        raise HTTPException(status_code=401, detail="Token has neither email nor phone_number claim")

    # Check if user already exists (by whichever identifier matched the token)
    if token_email:
        existing_user = await get_user_by_email(token_email, db)
        if existing_user:
            logger.warning(f"Email already registered: {token_email}")
            raise HTTPException(status_code=400, detail="Email already registered")
    else:
        result = await db.execute(select(User).where(User.phone_number == token_phone))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            logger.warning(f"Phone number already registered: {token_phone}")
            raise HTTPException(status_code=400, detail="Phone number already registered")

    try:
        # Create user in PostgreSQL — persist whichever identifier the token carried.
        logger.info("Creating user in PostgreSQL...")
        db_user = User(
            email=token_email,
            phone_number=token_phone,
            firebase_uid=decoded_token["uid"],
            is_active=True
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        logger.info(f"PostgreSQL user created with ID: {db_user.id}")

        return db_user

    except Exception as e:
        logger.error(f"Error during registration: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

# TODO: add a function to update user profile
# which will update the bio, interests, age, etc field in the User class
