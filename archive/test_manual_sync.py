#!/usr/bin/env python3
"""
Manually trigger the sync service to test matches table population
"""

import asyncio
import os
import sys
from datetime import datetime

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.services.firebase_sync_service import FirebaseSyncService

async def test_manual_sync():
    """Manually trigger the sync service"""
    
    print("🔄 Manually triggering Firebase sync service...")
    print("=" * 60)
    
    try:
        # Initialize Firebase sync service
        sync_service = FirebaseSyncService()
        
        # Manually trigger the sync
        print("📡 Running sync_matches_to_conversations...")
        await sync_service.sync_matches_to_conversations()
        
        print("✅ Sync completed successfully!")
        
    except Exception as e:
        print(f"❌ Error during sync: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_manual_sync()) 