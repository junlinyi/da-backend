# app/firebase.py

import base64
import json
import logging
import os
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, auth, messaging  # messaging used by push_notification_service
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

def _load_credentials() -> credentials.Certificate:
    """Load Firebase credentials from env var (production) or file (local dev)."""
    b64 = os.getenv("FIREBASE_CREDENTIALS_B64")
    if b64:
        # Production path: JSON is base64-encoded in an env var (no file on disk)
        cred_dict = json.loads(base64.b64decode(b64))
        logger.info("Firebase initialized from FIREBASE_CREDENTIALS_B64 env var")
        return credentials.Certificate(cred_dict)

    # Local dev fallback: read from file path
    project_root = Path(__file__).parent.parent
    cred_path = os.getenv(
        "FIREBASE_CREDENTIAL_PATH",
        str(project_root / "facedate-6616e-ebf102022977.json")
    )
    logger.info(f"Firebase initialized with credentials from: {cred_path}")
    return credentials.Certificate(cred_path)

if not firebase_admin._apps:
    firebase_admin.initialize_app(_load_credentials())
