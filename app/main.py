# app/main.py

import asyncio
import firebase_admin
from firebase_admin import credentials
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, users, matchmaking, sync, messaging, scheduling, video_calls
from app.services.firebase_sync_service import start_background_sync, stop_background_sync
from app.services.scheduling_monitor_service import start_scheduling_monitor, stop_scheduling_monitor
import os
from pathlib import Path
from dotenv import load_dotenv
from typing import List

# Load environment variables from .env file
load_dotenv()

# Initialize Firebase
try:
    # Try to get existing app
    firebase_admin.get_app()
    print("✅ Firebase already initialized")
except ValueError:
    # Initialize Firebase with service account
    project_root = Path(__file__).parent.parent
    cred_path = os.getenv(
        "FIREBASE_CREDENTIAL_PATH",
        str(project_root / "facedate-6616e-ebf102022977.json")
    )
    
    try:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        print(f"✅ Firebase initialized with credentials from: {cred_path}")
    except FileNotFoundError:
        print(f"❌ Firebase credentials file not found at: {cred_path}")
        print("Please set FIREBASE_CREDENTIAL_PATH environment variable or place credentials file in project root")
        raise

app = FastAPI(title="Dating App API", version="1.0.0")

# Configure CORS
# ALLOWED_ORIGINS env var: comma-separated list of allowed origins.
# Wildcard "*" is supported only without credentials (mobile/local dev).
# For web clients using cookies/credentials, set specific origins in ALLOWED_ORIGINS.
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
_allowed_origins: List[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]
_use_wildcard = not _allowed_origins  # fallback to wildcard if none specified
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins if not _use_wildcard else ["*"],
    # allow_credentials requires specific origins; incompatible with wildcard per CORS spec
    allow_credentials=not _use_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/users", tags=["Users"])
app.include_router(matchmaking.router, prefix="/matchmaking", tags=["Matchmaking"])
app.include_router(sync.router, prefix="/sync", tags=["Sync"])
app.include_router(messaging.router, prefix="/messaging", tags=["Messaging"])
app.include_router(scheduling.router, prefix="/scheduling", tags=["Scheduling"])
app.include_router(video_calls.router)

@app.on_event("startup")
async def startup_event():
    """Start background services when app starts"""
    # Start Firebase sync service
    asyncio.create_task(start_background_sync())
    
    # Start scheduling monitor service
    asyncio.create_task(start_scheduling_monitor())

@app.on_event("shutdown")
async def shutdown_event():
    """Stop background services when app shuts down"""
    await stop_background_sync()
    await stop_scheduling_monitor()

@app.get("/")
async def root():
    return {"message": "Dating App API is running!"}