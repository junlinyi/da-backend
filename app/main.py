# app/main.py

from fastapi import FastAPI
from routers import auth, users, matchmaking
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.include_router(auth.router, prefix="/auth")
app.include_router(users.router, prefix="/users")
app.include_router(matchmaking.router, prefix="/matchmaking")

@app.get("/")
async def root():
    return {"message": "Welcome to the dating app API"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or restrict to just your Expo dev IP if you want
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)