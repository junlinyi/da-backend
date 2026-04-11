# app/firebase.py

import firebase_admin
from firebase_admin import credentials, auth
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get the project root directory
project_root = Path(__file__).parent.parent

# Set the default path relative to the project root
cred_path = os.getenv(
    "FIREBASE_CREDENTIAL_PATH",
    str(project_root / "facedate-6616e-ebf102022977.json")
)

if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        print(f"✅ Firebase initialized with credentials from: {cred_path}")
    except FileNotFoundError:
        print(f"❌ Firebase credentials file not found at: {cred_path}")
        print("Please set FIREBASE_CREDENTIAL_PATH environment variable or place credentials file in project root")
        raise
