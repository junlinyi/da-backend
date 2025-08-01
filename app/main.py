# app/main.py

import asyncio
import firebase_admin
from firebase_admin import credentials
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, users, matchmaking, sync, messaging, scheduling
from app.services.firebase_sync_service import start_background_sync, stop_background_sync
from app.services.scheduling_monitor_service import start_scheduling_monitor, stop_scheduling_monitor

# Initialize Firebase
try:
    # Try to get existing app
    firebase_admin.get_app()
    print("✅ Firebase already initialized")
except ValueError:
    # Initialize Firebase with service account
    cred = credentials.Certificate("facedate-6616e-ebf102022977.json")
    firebase_admin.initialize_app(cred)
    print("✅ Firebase initialized with service account")

app = FastAPI(title="Dating App API", version="1.0.0")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
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