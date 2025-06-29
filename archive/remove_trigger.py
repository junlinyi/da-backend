#!/usr/bin/env python3
"""
Remove the trigger that's causing ON CONFLICT errors
"""

import asyncio
import os
import sys
from sqlalchemy import text

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.database import engine

async def remove_trigger():
    print("🔧 Removing trigger that's causing ON CONFLICT errors...")
    print("=" * 60)
    
    try:
        async with engine.begin() as conn:
            # Drop the trigger
            await conn.execute(text("DROP TRIGGER IF EXISTS trigger_create_conversation ON matches"))
            print("✅ Dropped trigger_create_conversation")
            
            # Drop the function (optional, but clean)
            await conn.execute(text("DROP FUNCTION IF EXISTS create_conversation_for_match()"))
            print("✅ Dropped create_conversation_for_match function")
            
        print("✅ Trigger and function removed successfully!")
        
    except Exception as e:
        print(f"❌ Error removing trigger: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(remove_trigger()) 