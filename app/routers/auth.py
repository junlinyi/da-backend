# app/routers/auth.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import User
from schemas import UserCreate, UserResponse
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordRequestForm

router = APIRouter(prefix="/auth", tags=["Auth"])

async def get_user_by_email(email: str, db: AsyncSession):
    """
    Using email as unique identifier, get the user object.
    """
    result = await db.execute(
        select(User).where(User.email == email)
    )
    return result.scalar_one_or_none()

# TODO: add a function to update user profile
# which will update the bio, interests, age, etc field in the User class
