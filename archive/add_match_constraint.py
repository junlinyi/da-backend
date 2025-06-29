#!/usr/bin/env python3
"""
Add unique constraint to matches table
"""

import asyncio
import os
import sys
from sqlalchemy import text

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.database import engine

async def add_match_constraint():
    """Add unique constraint to matches table"""
    
    print("🔧 Adding unique constraint to matches table...")
    print("=" * 60)
    
    try:
        async with engine.begin() as conn:
            # Add unique constraint
            await conn.execute(text("""
                ALTER TABLE matches 
                ADD CONSTRAINT uq_user_matched_user 
                UNIQUE (user_id, matched_user_id)
            """))
            
        print("✅ Unique constraint added successfully!")
        
    except Exception as e:
        if "already exists" in str(e):
            print("✅ Constraint already exists!")
        else:
            print(f"❌ Error adding constraint: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(add_match_constraint()) 