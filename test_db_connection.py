import asyncio
from app.database import engine, SessionLocal
from app.models import UserDefaultAvailability, User
from sqlalchemy import select, delete
from datetime import datetime

async def test_database():
    print("🔍 Testing database connection...")
    
    # Test 1: Check if we can connect and query
    async with engine.begin() as conn:
        result = await conn.execute(select(UserDefaultAvailability).where(UserDefaultAvailability.user_id == 75))
        records = result.fetchall()
        print(f"✅ Found {len(records)} existing availability records for user 75")
    
    # Test 2: Try to insert a record directly
    async with SessionLocal() as session:
        try:
            # Check if user exists
            user_result = await session.execute(select(User).where(User.id == 75))
            user = user_result.scalars().first()
            if not user:
                print("❌ User 75 not found")
                return
            
            print(f"✅ User found: {user.name} ({user.email})")
            
            # Delete existing records
            await session.execute(
                delete(UserDefaultAvailability).where(UserDefaultAvailability.user_id == 75)
            )
            
            # Insert a test record
            test_slot = UserDefaultAvailability(
                user_id=75,
                day_of_week=1,
                hour=10,
                minute=0,
                is_available=True
            )
            session.add(test_slot)
            
            # Commit the transaction
            await session.commit()
            print("✅ Successfully inserted test availability record")
            
            # Verify it was saved
            result = await session.execute(select(UserDefaultAvailability).where(UserDefaultAvailability.user_id == 75))
            records = result.scalars().all()
            print(f"✅ Found {len(records)} availability records after insert")
            
            for record in records:
                print(f"   - Day {record.day_of_week}, Hour {record.hour}:{record.minute:02d}, Available: {record.is_available}")
                
        except Exception as e:
            print(f"❌ Error: {e}")
            await session.rollback()

if __name__ == "__main__":
    asyncio.run(test_database()) 