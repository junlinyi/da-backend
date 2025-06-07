# app/firebase.py

import firebase_admin
from firebase_admin import credentials, auth
import os
from pathlib import Path

# Get the project root directory
project_root = Path(__file__).parent.parent

# Set the default path relative to the project root
cred_path = os.getenv(
    "FIREBASE_CREDENTIAL_PATH",
    str(project_root / "facedate-6616e-firebase-adminsdk.json")
)

if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)
