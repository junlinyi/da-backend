#!/usr/bin/env python3
"""
Migration script to update scheduling tables to simplified design.
Removes is_available and override_type columns, simplifies the schema.
"""

import asyncio
import sys
import os
from datetime import datetime, time
from sqlalchemy import text, create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Add the app directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import DATABASE_URL
from app.models import Base

async def migrate_scheduling_tables():
    """Migrate scheduling tables to simplified design."""
    
    # Get database URL
    database_url = DATABASE_URL
    
    # Create async engine
    engine = create_async_engine(database_url, echo=True)
    
    async with engine.begin() as conn:
        print("🔄 Starting scheduling tables migration...")
        
        # 1. Update user_weekly_availability table
        print("📅 Updating user_weekly_availability table...")
        await conn.execute(text("""
            -- Remove is_available column if it exists
            ALTER TABLE user_weekly_availability 
            DROP COLUMN IF EXISTS is_available;
        """))
        
        # 2. Update user_availability_overrides table
        print("📅 Updating user_availability_overrides table...")
        await conn.execute(text("""
            -- Remove is_available and override_type columns if they exist
            ALTER TABLE user_availability_overrides 
            DROP COLUMN IF EXISTS is_available;
        """))
        
        await conn.execute(text("""
            ALTER TABLE user_availability_overrides 
            DROP COLUMN IF EXISTS override_type;
        """))
        
        # 3. Update user_scheduling_preferences table
        print("⚙️ Updating user_scheduling_preferences table...")
        await conn.execute(text("""
            -- Remove preferred_call_duration column (fixed at 15 minutes)
            ALTER TABLE user_scheduling_preferences 
            DROP COLUMN IF EXISTS preferred_call_duration;
        """))
        
        # 4. Update scheduled_calls table
        print("📞 Updating scheduled_calls table...")
        await conn.execute(text("""
            -- Ensure duration_minutes is fixed at 15
            UPDATE scheduled_calls 
            SET duration_minutes = 15 
            WHERE duration_minutes != 15;
        """))
        
        # 5. Add constraints to enforce fixed duration
        await conn.execute(text("""
            -- Add check constraint to ensure duration is always 15 minutes
            ALTER TABLE scheduled_calls 
            ADD CONSTRAINT check_duration_15_minutes 
            CHECK (duration_minutes = 15);
        """))
        
        print("✅ Migration completed successfully!")
        
        # 6. Show summary of changes
        print("\n📋 Migration Summary:")
        print("- Removed is_available from user_weekly_availability")
        print("- Removed is_available and override_type from user_availability_overrides")
        print("- Removed preferred_call_duration from user_scheduling_preferences")
        print("- Fixed all scheduled_calls to 15 minutes duration")
        print("- Added constraint to enforce 15-minute calls")
        
        # 7. Show table structure
        print("\n📊 Updated table structures:")
        
        # Check weekly availability structure
        result = await conn.execute(text("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'user_weekly_availability' 
            ORDER BY ordinal_position;
        """))
        print("\nuser_weekly_availability:")
        for row in result:
            print(f"  - {row[0]}: {row[1]} ({'NULL' if row[2] == 'YES' else 'NOT NULL'})")
        
        # Check overrides structure
        result = await conn.execute(text("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'user_availability_overrides' 
            ORDER BY ordinal_position;
        """))
        print("\nuser_availability_overrides:")
        for row in result:
            print(f"  - {row[0]}: {row[1]} ({'NULL' if row[2] == 'YES' else 'NOT NULL'})")
        
        # Check preferences structure
        result = await conn.execute(text("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'user_scheduling_preferences' 
            ORDER BY ordinal_position;
        """))
        print("\nuser_scheduling_preferences:")
        for row in result:
            print(f"  - {row[0]}: {row[1]} ({'NULL' if row[2] == 'YES' else 'NOT NULL'})")

async def test_simplified_schema():
    """Test the simplified schema with sample data."""
    
    database_url = DATABASE_URL
    engine = create_async_engine(database_url, echo=False)
    
    async with engine.begin() as conn:
        print("\n🧪 Testing simplified schema...")
        
        # Test 1: Insert weekly availability (no is_available needed)
        print("Test 1: Inserting weekly availability...")
        await conn.execute(text("""
            INSERT INTO user_weekly_availability (user_id, day_of_week, start_time, end_time)
            VALUES (1, 1, '18:00:00', '22:00:00')
            ON CONFLICT (user_id, day_of_week, start_time, end_time) DO NOTHING;
        """))
        
        # Test 2: Insert override (no is_available or override_type needed)
        print("Test 2: Inserting availability override...")
        await conn.execute(text("""
            INSERT INTO user_availability_overrides (user_id, date, start_time, end_time, reason)
            VALUES (1, '2024-03-20', '14:00:00', '18:00:00', 'Working from home')
            ON CONFLICT (user_id, date, start_time, end_time) DO NOTHING;
        """))
        
        # Test 3: Insert scheduling preferences (no preferred_call_duration)
        print("Test 3: Inserting scheduling preferences...")
        await conn.execute(text("""
            INSERT INTO user_scheduling_preferences (user_id, max_calls_per_week, min_notice_hours, max_advance_days, preferred_start_time, preferred_end_time)
            VALUES (1, 5, 2, 7, '18:00:00', '22:00:00')
            ON CONFLICT (user_id) DO NOTHING;
        """))
        
        print("✅ All tests passed!")

if __name__ == "__main__":
    print("🚀 Starting Simplified Scheduling Migration")
    print("=" * 50)
    
    try:
        asyncio.run(migrate_scheduling_tables())
        asyncio.run(test_simplified_schema())
        print("\n🎉 Migration completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        sys.exit(1) 