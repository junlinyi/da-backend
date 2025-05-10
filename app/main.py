# app/main.py

from fastapi import FastAPI
from app.routers import auth, users, matchmaking
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "exp://localhost:19000",
        "exp://localhost:8081",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth")
app.include_router(users.router, prefix="/users")
app.include_router(matchmaking.router, prefix="/matchmaking")

@app.get("/")
async def root():
    return {"message": "Welcome to the dating app API"}