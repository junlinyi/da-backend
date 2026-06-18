# app/main.py

import asyncio
import json
import logging
import logging.config
import os
import sys
from pathlib import Path
from typing import List

import firebase_admin
from firebase_admin import credentials
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.limiter import limiter
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ── Structured JSON logging (INFRA-04) ───────────────────────────────────────
# In production, emit JSON so log aggregators (Datadog, CloudWatch, etc.) can
# parse fields directly. In development, use the human-readable format.
_log_env = os.getenv("ENVIRONMENT", "development").lower()
_log_level = os.getenv("LOG_LEVEL", "INFO").upper()

class _JsonFormatter(logging.Formatter):
    """Single-line JSON log records."""
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)

import re as _re

class _RedactBirthdateFilter(logging.Filter):
    """Birthdate is PII (AGE_VERIFICATION_SPEC.md Security Review). We never log it
    intentionally, but this filter is a backstop: it masks any value attached to a
    `birthdate` / `proposed_birthdate` / `current_birthdate` key in a log message,
    without touching unrelated dates (created_at, scheduled times, etc.)."""
    _PATTERN = _re.compile(
        r"((?:proposed_|current_)?birthdate)"      # the key
        r"(['\"]?\s*[=:]\s*['\"]?)"                 # = or : with optional quotes
        r"\d{4}-\d{2}-\d{2}"                        # the ISO date value
    )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            if "birthdate" in msg:
                record.msg = self._PATTERN.sub(r"\1\2<redacted>", msg)
                record.args = ()
        except Exception:
            pass
        return True

_handler = logging.StreamHandler(sys.stdout)
if _log_env == "production":
    _handler.setFormatter(_JsonFormatter())
else:
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
_handler.addFilter(_RedactBirthdateFilter())

logging.root.setLevel(_log_level)
logging.root.handlers = [_handler]
# Quieten noisy third-party loggers
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

from app.routers import auth, users, matchmaking, sync, messaging, scheduling, video_calls, reporting, admin
from app.routers import questionnaire
from app.routers import matches
from app.routers import deletion_reasons
from app.routers import birthdate_change_requests
from app.services.firebase_sync_service import start_background_sync, stop_background_sync
from app.services.scheduling_monitor_service import start_scheduling_monitor, stop_scheduling_monitor, start_fast_monitor

# ── Sentry error tracking (INFRA-05) ─────────────────────────────────────────
# Set SENTRY_DSN in .env to enable. Safe to leave unset in development.
_sentry_dsn = os.getenv("SENTRY_DSN")
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    sentry_sdk.init(
        dsn=_sentry_dsn,
        environment=os.getenv("ENVIRONMENT", "development"),
        traces_sample_rate=0.1,   # 10% of requests traced for performance
        profiles_sample_rate=0.1,
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        # Don't send PII like user emails
        send_default_pii=False,
    )
    logger.info(f"Sentry initialized (environment={os.getenv('ENVIRONMENT', 'development')})")
else:
    logger.info("SENTRY_DSN not set — error tracking disabled")

# Initialize Firebase
try:
    # Try to get existing app
    firebase_admin.get_app()
    logger.info("Firebase already initialized")
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
        logger.info(f"Firebase initialized with credentials from: {cred_path}")
    except FileNotFoundError:
        logger.error(f"Firebase credentials file not found at: {cred_path}")
        raise

app = FastAPI(title="Dating App API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Configure CORS
# ALLOWED_ORIGINS env var: comma-separated list of allowed origins.
# In production, this MUST be set — starting without it raises a RuntimeError.
# In local development (ENVIRONMENT=development), it defaults to localhost origins only.
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
_allowed_origins: List[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]
# Default to development mode so local dev servers start without ALLOWED_ORIGINS set.
# Production deployments MUST set ENVIRONMENT=production — the startup check enforces this.
_environment = os.getenv("ENVIRONMENT", "development").lower()

if not _allowed_origins:
    if _environment == "production":
        raise RuntimeError(
            "ALLOWED_ORIGINS environment variable is not set. "
            "Set it to a comma-separated list of allowed origins (e.g. https://yourdomain.com). "
            "Refusing to start in production with wildcard CORS."
        )
    else:
        # Safe dev defaults — localhost only, never wildcard
        _allowed_origins = ["http://localhost:3000", "http://localhost:8080", "http://127.0.0.1:3000"]
        logger.warning(
            "ALLOWED_ORIGINS not set — using localhost-only CORS defaults. "
            "Set ENVIRONMENT=production and ALLOWED_ORIGINS in production."
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/users", tags=["Users"])
app.include_router(birthdate_change_requests.router, prefix="/users", tags=["Age Verification"])
app.include_router(matchmaking.router, prefix="/matchmaking", tags=["Matchmaking"])
app.include_router(sync.router, prefix="/sync", tags=["Sync"])
app.include_router(messaging.router, prefix="/messaging", tags=["Messaging"])
app.include_router(scheduling.router, prefix="/scheduling", tags=["Scheduling"])
app.include_router(video_calls.router)
app.include_router(reporting.router, prefix="/reports", tags=["Reporting"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(questionnaire.router, prefix="/questionnaire", tags=["Questionnaire"])
app.include_router(matches.router)
app.include_router(deletion_reasons.router, tags=["Account Deletion"])

def _validate_required_env_vars() -> None:
    """Raise RuntimeError on startup if critical environment variables are missing.

    DATABASE_URL is excluded because database.py provides a localhost fallback
    for local development. All other secrets must be explicitly set.
    """
    required = {
        "FIREBASE_CREDENTIAL_PATH": os.getenv("FIREBASE_CREDENTIAL_PATH"),
        "TWILIO_ACCOUNT_SID": os.getenv("TWILIO_ACCOUNT_SID"),
        "TWILIO_API_KEY": os.getenv("TWILIO_API_KEY"),
        "TWILIO_API_SECRET": os.getenv("TWILIO_API_SECRET"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing and _environment == "production":
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Copy .env.example to .env and fill in all values."
        )
    elif missing:
        logger.warning(f"[DEV] Missing env vars (would fail in production): {', '.join(missing)}")

_validate_required_env_vars()


@app.on_event("startup")
async def startup_event():
    """Start background services when app starts"""
    # Create any new database tables (safe: checkfirst skips existing tables)
    from app.database import engine, Base
    import app.models  # ensure all models are registered  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)

    # Start Firebase sync service
    asyncio.create_task(start_background_sync())

    # Start scheduling monitor service (slow loop: expiry + no-show, 300s)
    asyncio.create_task(start_scheduling_monitor())

    # Start the fast scheduling loop (text-lock + pre-lock nudges, 60s)
    asyncio.create_task(start_fast_monitor())

@app.on_event("shutdown")
async def shutdown_event():
    """Stop background services when app shuts down"""
    await stop_background_sync()
    await stop_scheduling_monitor()

@app.get("/")
async def root():
    return {"message": "Dating App API is running!"}


@app.get("/health")
async def health_check():
    """Liveness + DB readiness probe. Returns 200 if the DB is reachable."""
    from app.database import get_db
    from sqlalchemy import text
    db_status = "unknown"
    try:
        async for db in get_db():
            await db.execute(text("SELECT 1"))
            db_status = "connected"
            break
    except Exception as exc:
        logger.error(f"Health check DB probe failed: {exc}")
        db_status = "error"
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "db": db_status},
        )
    return {"status": "ok", "db": db_status}