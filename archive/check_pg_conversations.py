#!/usr/bin/env python3

import asyncio
from sqlalchemy import text
from app.database import get_db

async def check_pg_conversations():
    # Get database session
    db = await anext(get_db())
    
    try:
        # Check PostgreSQL conversations
        print("=== POSTGRESQL CONVERSATIONS ===")
        result = await db.execute(text("SELECT * FROM conversations ORDER BY created_at DESC LIMIT 10"))
        pg_conversations = result.fetchall()
        
        if pg_conversations:
            for conv in pg_conversations:
                print(f"ID: {conv[0]}, User1: {conv[1]}, User2: {conv[2]}, Created: {conv[3]}")
                print(f"  Last Message: {conv[4]}, Last Message At: {conv[5]}")
                print(f"  User1 Unread: {conv[6]}, User2 Unread: {conv[7]}, Active: {conv[8]}")
                print()
        else:
            print("No conversations found in PostgreSQL")
            
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(check_pg_conversations()) 