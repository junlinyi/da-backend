# Dating App - Python Backend

## Project Overview
FastAPI backend for the dating app. iOS frontend is at `../DatingAppProj/`.

## Architecture
- **Framework**: FastAPI (Python 3.13)
- **Database**: PostgreSQL (via Docker, user=dating_user, db=dating_app)
- **ORM**: SQLAlchemy
- **Auth**: Firebase Admin SDK (verify ID tokens); project `facedate-6616e` is on the **Blaze plan** — required for Storage (Spark plan dropped Storage support)
- **Video**: Twilio Video SDK (token generation, room management)
- **Validation**: Pydantic v2

## Project Structure
```
app/
├── main.py               # FastAPI app entry point
├── dependencies.py        # Auth dependency (verify_firebase_token)
├── schemas.py             # Pydantic models (ScheduledCallCreate, ScheduledCallResponse, etc.)
├── models.py              # SQLAlchemy ORM models
├── routers/
│   ├── scheduling.py      # Scheduling endpoints (/scheduling/*)
│   ├── video_calls.py     # Video call endpoints (/video-calls/*)
│   ├── users.py           # User endpoints
│   └── ...
└── ...
```

## Key Endpoints
- `POST /scheduling/calls` — Create a scheduled call (expects ScheduledCallCreate)
- `GET /scheduling/me/calls` — Get user's scheduled calls
- `POST /scheduling/call-requests` — Tier 1 (immediate call request, 5-min TTL)
- `POST /scheduling/proposals` — Tier 2 (time-block proposal)
- `GET /scheduling/me/matches` — Get user's matches
- `POST /video-calls/token` — Generate Twilio video token
- `POST /video-calls/rooms` — Create video room

## Database
- Connect: `docker exec -it <container> psql -U dating_user -d dating_app`
- Key tables: `users`, `matches`, `swipes`, `conversations`, `messages`, `scheduled_calls`, `call_requests`, `scheduling_proposals`, `proposal_time_slots`, `proposal_responses`, `counter_proposal_time_slots`, `call_ratings`, `video_call_rooms`, `reports`, `user_values`, `user_feature_vectors`, `behavioral_events`, `match_outcomes`, `user_scheduling_preferences`

## Timezone Convention
- All times stored and calculated in UTC
- Frontend sends ISO 8601 with timezone info
- `datetime.now(timezone.utc)` for current time (NOT `datetime.utcnow()`)

## Running the Server
```bash
cd /Users/junlinyi/GitHub2/da-backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Environment
- Credentials in `.env` (Firebase, Twilio, DB connection)
- Firebase service account: `facedate-6616e-ebf102022977.json`

## Known Issues (as of Apr 2026)
- `POST /scheduling/calls` returns 409 when existing calls overlap, even if they're already `completed` or `cancelled`
- Timezone-naive vs timezone-aware datetime comparisons in some validators

## Work Logging
When running autonomously (headless/queue mode), ALWAYS append a summary of your work to `WORK_LOG.md` in the project root before finishing. Format:

```
## [DATE] Task: <brief title>
**Branch:** <branch name>
**Files Modified:**
- `path/to/file.py` — what was changed and why

**Summary:** 1-3 sentences describing what was accomplished.
**Status:** completed / partial / blocked (and why)
---
```

## Safety Rules
- NEVER modify .env or credential files
- NEVER expose API keys or secrets in code
- NEVER force-push to main
- ALWAYS create a branch for changes
- ALWAYS test endpoints after changes (use curl or the test scripts)
