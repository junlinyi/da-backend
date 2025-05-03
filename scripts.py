from app.database import SessionLocal
from app.models import User  # Assuming you have a User model
import asyncio

async def seed_db():
    async with SessionLocal() as session:
        user = User(username="testuser", email="test@example.com", hashed_password="hashedpassword")
        session.add(user)
        await session.commit()

asyncio.run(seed_db())
