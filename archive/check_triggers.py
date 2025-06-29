#!/usr/bin/env python3
"""
Check if the create_conversation_for_match trigger is installed and causing issues
"""

import asyncio
import os
import sys
from sqlalchemy import text

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.database import engine

async def check_triggers():
    print("🔍 Checking for triggers on matches table...")
    print("=" * 60)
    
    async with engine.begin() as conn:
        # Check for triggers on matches table
        result = await conn.execute(text("""
            SELECT trigger_name, event_manipulation, action_statement
            FROM information_schema.triggers
            WHERE event_object_table = 'matches'
        """))
        triggers = result.fetchall()
        
        if triggers:
            print("❌ Found triggers on matches table:")
            for trigger in triggers:
                print(f"  Name: {trigger[0]}")
                print(f"  Event: {trigger[1]}")
                print(f"  Action: {trigger[2]}")
                print()
        else:
            print("✅ No triggers found on matches table")
        
        # Check for the specific function
        result = await conn.execute(text("""
            SELECT routine_name, routine_definition
            FROM information_schema.routines
            WHERE routine_name = 'create_conversation_for_match'
        """))
        functions = result.fetchall()
        
        if functions:
            print("❌ Found create_conversation_for_match function:")
            for func in functions:
                print(f"  Name: {func[0]}")
                print(f"  Definition: {func[1][:200]}...")
                print()
        else:
            print("✅ No create_conversation_for_match function found")
    
    print("Done.")

if __name__ == "__main__":
    asyncio.run(check_triggers()) 