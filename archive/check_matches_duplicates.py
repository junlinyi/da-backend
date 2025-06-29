#!/usr/bin/env python3
"""
Check for duplicate (user_id, matched_user_id) pairs and list constraints on the matches table
"""

import asyncio
import os
import sys
from sqlalchemy import text

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.database import engine

async def check_duplicates_and_constraints():
    print("🔍 Checking for duplicate (user_id, matched_user_id) pairs in matches table...")
    print("=" * 60)
    async with engine.begin() as conn:
        # Check for duplicates
        result = await conn.execute(text('''
            SELECT user_id, matched_user_id, COUNT(*) as count
            FROM matches
            GROUP BY user_id, matched_user_id
            HAVING COUNT(*) > 1
        '''))
        duplicates = result.fetchall()
        if duplicates:
            print("❌ Found duplicate pairs:")
            for row in duplicates:
                print(f"  user_id={row[0]}, matched_user_id={row[1]}, count={row[2]}")
        else:
            print("✅ No duplicate pairs found.")
        print()
        # List constraints
        print("🔗 Listing constraints on matches table:")
        result = await conn.execute(text('''
            SELECT conname, contype, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'matches'::regclass
        '''))
        constraints = result.fetchall()
        for row in constraints:
            print(f"  Name: {row[0]}, Type: {row[1]}, Def: {row[2]}")
    print("\nDone.")

if __name__ == "__main__":
    asyncio.run(check_duplicates_and_constraints()) 