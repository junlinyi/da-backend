import asyncio
from app.database import get_db
from app.models import User

async def check_user():
    db = await anext(get_db())
    users = db.query(User).filter(User.firebase_uid == 'kYVH2LYwT5dbsH2PsOE5haqXMUu1').all()
    print(f'User found in PostgreSQL: {len(users) > 0}')
    for user in users:
        print(f'User: {user.name}, {user.email}')

if __name__ == "__main__":
    asyncio.run(check_user()) 