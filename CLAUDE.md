# Dating App - Python Backend

## Project Overview
FastAPI backend for the dating app. iOS frontend is at `../DatingAppProj/`.

## Architecture
- **Framework**: FastAPI (Python 3.13)
- **Database**: PostgreSQL (via Docker, user=dating_user, db=dating_app)
- **ORM**: SQLAlchemy (async). Migrations via **Alembic** (`alembic/versions/`)
- **Auth**: Firebase Admin SDK (verify ID tokens); project `facedate-6616e` is on the **Blaze plan** — required for Storage (Spark plan dropped Storage support)
- **Video**: Twilio Video SDK (token generation, room management)
- **Chat**: **Firestore-authoritative** for real-time delivery + push; Postgres `messages` is an analytics mirror (see Scheduling V2 below)
- **Validation**: Pydantic v2

## Scheduling (V2 — current, shipped 2026-06)
The scheduling system is **SCHEDULING_V2** (canonical spec: [`../DatingAppProj/SCHEDULING_V2.md`](../DatingAppProj/SCHEDULING_V2.md), with an "As-Built" section documenting how the implementation diverged from the spec). It **replaced** the legacy two-tier system (Tier-1 immediate `call_requests` + Tier-2 `scheduling_proposals`), which is fully removed. The old availability-grid design doc `scheduling_design.md` is **superseded/dead**.

V2 model — a match has **three orthogonal state dimensions** on the `matches` row:
- `text_state` ∈ `open | locked | archived` (chat input gate; opens for 24h after match, then auto-locks)
- `call_status` ∈ `none | proposal_pending | scheduled | in_progress | pending_survey | completed | no_show`
- `lifecycle` ∈ `active | terminated | expired`

Key backend pieces:
- **`app/services/match_state_service.py`** — the state machine: legal-transition tables (`is_legal_call_status`/`is_legal_text_state`), row-locked DB transitions (`transition_call_status`, `transition_text_state`, `process_exit_survey`, `record_no_show`), `compute_match_card_display`, system-message writer, and the cron bodies.
- **`app/routers/scheduling.py`** — propose/accept/counter + read endpoints (see Key Endpoints).
- **`app/routers/matches.py`** — exit-survey / contact / reveal-contact endpoints (prefix `/matches`).
- **`app/routers/video_calls.py`** — Twilio token/rooms (reused) + call-lifecycle hooks: joining `/rooms` flips `scheduled → in_progress` (and bumps `total_calls_completed`); `end_call` flips `→ pending_survey` + fires `exit_survey_prompt`. `POST /video-calls/{id}/debug-advance` (non-prod only) drives the lifecycle for sim E2E.
- **`app/routers/messaging.py`** — `send_message` enforces the text-lock (403 when `text_state != open`), applies the phone-mask stub, and is the **single masking authority**: it returns the masked content + `has_masked_content`; the iOS client writes that masked content to Firestore (backend does NOT double-write Firestore). Mirrors to Postgres for analytics.
- **`app/services/chat_message_filter.py`** — phone-number mask **stub** (`filter_message_content`); full algorithm deferred to a moderation spec.
- **Crons** (`app/services/scheduling_monitor_service.py`, started in `main.py`): a **60s fast loop** (`lock_text_for_eligible_matches` at 24h + 5h/1h nudges) and the **300s loop** (`expire_unscheduled_matches` at 72h post-lock, `detect_no_shows` at 10-min grace, `match_expiring_soon` at 48h, date reminders).
- **Push**: `app/services/push_notification_service.py` — 16 V2 typed senders; copy uses "video date", and each sets `data.type` for iOS `NotificationRouter` routing.

## Project Structure
```
app/
├── main.py               # FastAPI app entry; starts both scheduling cron loops
├── dependencies.py        # Auth deps: verify_firebase_token (token dict) + get_current_user (User ORM)
├── schemas.py             # Pydantic v2 models (V2: ProposeCallRequest, VideoCallProposalResponse, MatchListItem, ExitSurveyResult, ContactResponse, ...)
├── models.py              # SQLAlchemy ORM (Match w/ 3 state dims, VideoCallProposal, NoShowEvent, ScheduledCall, ...)
├── routers/
│   ├── scheduling.py      # V2 scheduling endpoints (/scheduling/*)
│   ├── matches.py         # exit-survey / contact / reveal-contact (/matches/*)
│   ├── video_calls.py     # Twilio + call-lifecycle hooks (/video-calls/*)
│   ├── messaging.py       # Firestore chat send w/ text-lock + mask enforcement
│   └── ...
├── services/
│   ├── match_state_service.py        # V2 state machine + crons
│   ├── chat_message_filter.py        # phone-mask stub
│   ├── scheduling_monitor_service.py # cron loops (60s fast + 300s)
│   └── push_notification_service.py  # 16 V2 push senders
└── alembic/versions/      # migrations (V2: 58e992d1eb19_scheduling_v2, a1b2c3scjf01_scheduled_call_join_flags)
```

## Key Endpoints (V2)
Scheduling (`app/routers/scheduling.py`, all `Depends(get_current_user)`, participant-checked):
- `POST /scheduling/calls/propose` — propose a single 30-min slot (`{match_id, proposed_start_utc}`); 400 past/>72h, 409 if a pending proposal already exists (returns the active proposal in the body, Flow 6)
- `POST /scheduling/calls/{proposal_id}/accept` — accept (creates `ScheduledCall`, `call_status → scheduled`, bumps both users' `total_calls_scheduled`); 403 if proposer accepts own
- `POST /scheduling/calls/{proposal_id}/counter` — supersede + re-propose (only the non-proposer)
- `GET /scheduling/me/matches` — active matches with full 3-dim state + `card_display` + `peer_user` (incl. `peer_firebase_uid` for the iOS conversation join) + active proposal / scheduled call
- `GET /scheduling/me/upcoming-calls` — future scheduled calls
- `POST /scheduling/calls/{call_id}/no-show` — cron-facing; derives no-showers from the `user1_joined`/`user2_joined` flags (participant-only; no caller-supplied victim id)
- `GET /scheduling/me/calls`, `GET|PUT /scheduling/me/preferences` — retained
- `POST /matches/{match_id}/exit-survey` — yes/no; mutual-yes → `completed` + `contact_reveal_unlocked`
- `GET /matches/{match_id}/contact`, `POST /matches/{match_id}/reveal-contact` — gated on `contact_reveal_unlocked`
- `POST /messaging/conversations/{conversation_id}/messages` — chat send (text-lock 403 + mask); `POST /video-calls/token`, `POST /video-calls/rooms`, `POST /video-calls/{id}/end`

**Removed legacy endpoints (gone):** `POST /scheduling/calls`, `/scheduling/call-requests*` (Tier-1), `/scheduling/proposals*` (Tier-2), `extend_call`, `confirm_call`.

## Database
- Connect: `docker exec -it <container> psql -U dating_user -d dating_app` (creds `dating_user` / `securepassword`)
- Apply migrations: `DATABASE_URL=postgresql://dating_user:securepassword@localhost/dating_app alembic upgrade head`
- **V2 scheduling tables/columns:** `matches` (+ `text_state`, `call_status`, `lifecycle`, `text_locked_at`, `text_unlocked_at`, `expires_at`, `exit_survey_user_a/b_response(+_responded_at)`, `contact_reveal_unlocked`, `contact_revealed_to_user_a/b_at` + CHECK constraints + indexes incl. partial `idx_matches_active_needs_action`); **`video_call_proposals`** (partial-unique `idx_one_pending_proposal_per_match WHERE status='pending'`); **`no_show_events`**; `scheduled_calls` (+ `user1_joined`/`user2_joined`); `users` (+ `total_calls_scheduled`, `total_calls_completed`, `phone_country_code`); `messages` (`sender_id` now nullable for system messages, + `has_masked_content`, `system_message_type`).
- Other tables: `users`, `swipes`, `conversations`, `messages`, `call_ratings`, `video_call_rooms`, `reports`, `user_values`, `user_feature_vectors`, `behavioral_events`, `match_outcomes`, `user_scheduling_preferences`
- **Dropped by the V2 migration:** `call_requests`, `scheduling_proposals`, `proposal_time_slots`, `proposal_responses`, `counter_proposal_time_slots`, and the broken `trigger_update_call_preferences` trigger/function.
- **Seed:** `seed_scheduling_v2.sql` (idempotent; resets the V2 test matches). The older `seed_scheduling_audit.sql` was for the legacy schema.

## Tests
- V2 suites run against a **real Postgres test DB** (`dating_app_test`) via `tests/conftest_pg.py` (overrides `get_current_user`, no Firebase needed). Run: `source venv/bin/activate && pytest tests/test_scheduling_v2_*.py tests/test_match_state_*.py tests/test_messaging_gate.py tests/test_push_v2.py tests/test_video_lifecycle.py -q` (112 passing as of 2026-06).
- The legacy SQLite conftest (`tests/conftest.py`) remains for older suites; the dead `test_scheduling_{integration,e2e,regression}.py` were removed.

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

## Known Issues / Follow-ups (as of Jun 2026, post-V2)
- **Analytics mirror dedup:** the `send_message` handler mirrors a message row (NULL `firebase_id`), AND the background `firebase_sync_service` independently mirrors client Firestore docs (non-null `firebase_id`) — so the `messages` table can hold two rows per message, and the sync-service copy stamps `has_masked_content=false` regardless. Not user-facing; clean up before relying on `messages` for ML.
- **No-show join signal:** `record_no_show` reads `scheduled_calls.user1_joined`/`user2_joined`, which are set when a user hits `/video-calls/rooms`. Real Twilio "joined" detection (vs. just requesting a room) is coarse.
- **`total_calls_completed`** increments at the both-joined → `in_progress` edge (per spec wording), so a call that reaches in_progress but then no-shows still counts.
- Legacy obsolete (no longer apply): the Apr-2026 `POST /scheduling/calls` 409-on-completed-overlap and `find_common_availability`/`check_scheduling_conflict` timezone bugs — those endpoints/functions were removed with the two-tier system.

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
