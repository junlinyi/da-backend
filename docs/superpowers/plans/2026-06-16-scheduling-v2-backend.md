# Scheduling V2 — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy two-tier scheduling backend with SCHEDULING_V2's three-orthogonal-dimension match-state machine, single-time-slot video-date proposals, text-gating, exit survey, contact reveal, and per-user no-show tracking — fully tested end-to-end.

**Architecture:** Postgres is the source of truth for match state (`text_state` × `call_status` × `lifecycle`). A new `match_state_service.py` owns all legal transitions (pure functions for logic, DB-bound functions for persistence + row locks). Endpoints in a rewritten `scheduling.py` (+ small additions to `messaging.py`/`video_calls.py`) drive transitions. Chat stays **Firestore-authoritative** for real-time push; the existing `send_message` path gains a server-side text-lock gate + phone-mask stub + system-message writer, and continues mirroring to Postgres for analytics. Twilio video is reused unchanged; only the call lifecycle hooks (`in_progress`/`pending_survey`) are added. Crons run as asyncio loops in `scheduling_monitor_service.py`.

**Tech Stack:** FastAPI, async SQLAlchemy, Pydantic v2, Alembic, Postgres, Firebase Admin (Firestore + FCM), Twilio Video, pytest (`asyncio_mode=auto`).

**Source-of-truth spec:** [`../../../../DatingAppProj/SCHEDULING_V2.md`](../../../../DatingAppProj/SCHEDULING_V2.md) (backend lives in `da-backend`; spec lives in `DatingAppProj`).

**Branch:** `feature/scheduling-v2` (off `main`) — already created.

---

## Decisions locked (from session)

1. **Scope:** Full V2 scheduling/state-machine/text-gating. Real Twilio video left as-is; the call lifecycle transitions (`scheduled → in_progress → pending_survey`) are driven by the existing `video_calls` endpoints + a debug hook for E2E. Spec Non-Goals stay deferred: phone-mask is a **regex stub**, exit-survey is functional (yes/no) but its rich UX is deferred.
2. **Chat:** Firestore stays authoritative (real-time → push). V2 gating is **server-enforced in the `send_message` endpoint**: reject sends when `text_state != 'open'`, run the mask stub, write system messages as Firestore docs (`messageType:"system"`, plus `system_message_type`). Postgres `messages` mirror keeps analytics parity (sender_id nullable, new columns).
3. **Tests:** Real **Postgres test DB** for integration/E2E (new `conftest` harness with `get_current_user` override) + pure-function unit tests for the state machine. Delete the dead `test_scheduling_*.py`.

## Spec corrections baked into this plan (verified against code)

- `matches.expires_at` does **not** exist (spec wrongly calls it "existing") → migration **adds** it.
- `users.phone_country_code` does **not** exist (the `/contact` response needs it) → migration **adds** it (nullable).
- `users.no_show_count` + `last_no_show_at` **already exist** (reuse). Add `total_calls_scheduled`, `total_calls_completed`.
- `messages.sender_id` is currently **NOT NULL** → make nullable for system-message mirror rows.
- DB trigger `trigger_update_call_preferences` references a dropped table and 500s on `scheduled_calls` inserts → **drop it** in the migration.
- The "cron" is a single 5-min asyncio loop (`scheduling_monitor_service.check_all_matches`, `check_interval=300`) → add a **second 60-second loop** for text-lock + nudges.
- Alembic single head is **`b2c3d4e5f6a7`** → new migration's `down_revision`.
- Auth dep: `get_current_user` (`app/dependencies.py:31`) returns the **`User` ORM model**; use `user.id`. `verify_firebase_token` (`:16`) returns the decoded token dict (used by `messaging.py`).
- Twilio reuse anchors: `app/routers/video_calls.py:94` (`/rooms`), `:56` (`/token`), `:254` (`end_call`).

---

## File Structure

**Create:**
- `alembic/versions/<rev>_scheduling_v2.py` — schema migration (all V2 tables/columns + drops).
- `app/services/match_state_service.py` — the state machine (transitions + helpers + cron bodies for state changes).
- `app/services/chat_message_filter.py` — `filter_message_content()` mask **stub** (interface from spec §Service Logic).
- `seed_scheduling_v2.sql` — idempotent V2 seed for matches 57 (Alex↔Mia) & 60 (Jordan↔Riley).
- `tests/conftest_pg.py` (or extend `conftest.py`) — Postgres test harness + `get_current_user` override + V2 factories.
- `tests/test_match_state_unit.py` — pure state-machine unit tests.
- `tests/test_scheduling_v2_integration.py` — endpoint integration tests.
- `tests/test_scheduling_v2_crons.py` — cron tests (lock/expire/no-show).

**Modify:**
- `app/models.py` — add `VideoCallProposal`, `NoShowEvent`; add columns to `Match`, `User`, `Message`; remove 5 legacy model classes.
- `app/schemas.py` — add V2 schemas; remove legacy proposal/call-request schemas.
- `app/routers/scheduling.py` — add 5 V2 endpoints; remove legacy proposal + call-request + old `/me/matches` semantics.
- `app/routers/messaging.py` — add text-lock gate + mask + system-message writer to `send_message`.
- `app/routers/video_calls.py` — `end_call` drives `call_status → pending_survey` + `exit_survey_prompt`; add a `/calls/{id}/start` (or join) hook for `in_progress`.
- `app/routers/matches.py` (or wherever match routes live; if none, add to `scheduling.py` under `/matches` paths) — `exit-survey`, `contact`, `reveal-contact`.
- `app/services/scheduling_monitor_service.py` — replace legacy cron bodies with V2 (delegating to `match_state_service`); add the 60s loop.
- `app/services/push_notification_service.py` — add 16 V2 typed senders; remove legacy ones.
- `app/main.py` — start the second cron loop; keep `Base.metadata.create_all`.

**Delete:**
- `tests/test_scheduling_integration.py`, `tests/test_scheduling_e2e.py`, `tests/test_scheduling_regression.py` (dead — import nonexistent models).

---

## Phase 0 — Test harness & baseline

### Task 0.1: Create a Postgres test-DB fixture set

**Files:**
- Create: `tests/conftest_pg.py`
- Reference: `tests/conftest.py` (existing SQLite fixtures; we add a Postgres variant rather than break it)

- [ ] **Step 1: Add the harness.** Create `tests/conftest_pg.py`:

```python
"""Postgres-backed test harness for Scheduling V2.

Uses a dedicated test database so partial unique indexes / ARRAY / TIMESTAMPTZ
behave exactly as production. Auth is overridden so tests don't need Firebase.
"""
import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.database import Base
from app.dependencies import get_current_user, get_db
from app.main import app
from app import models

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://dating_user:securepassword@localhost/dating_app_test",
)

engine = create_async_engine(TEST_DB_URL, future=True)
TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with TestSession() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def make_user(db):
    async def _make(name="Test", firebase_uid=None, timezone="UTC", device_token="tok"):
        u = models.User(
            firebase_uid=firebase_uid or f"uid_{name.lower()}",
            name=name, timezone=timezone, device_token=device_token, is_active=True,
        )
        db.add(u); await db.commit(); await db.refresh(u)
        return u
    return _make


@pytest_asyncio.fixture
async def make_match(db):
    async def _make(user_a, user_b, **overrides):
        m = models.Match(
            user_id=user_a.id, matched_user_id=user_b.id, status="accepted",
            user1_status="active", user2_status="active", **overrides,
        )
        db.add(m); await db.commit(); await db.refresh(m)
        return m
    return _make


@pytest_asyncio.fixture
async def client_as(db):
    """Returns a factory: client_as(user) -> AsyncClient authed as that user."""
    def _as(user):
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: user
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    yield _as
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Create the test DB.** Run:

```bash
PGPASSWORD=securepassword createdb -h localhost -U dating_user dating_app_test 2>/dev/null || echo "exists"
```
Expected: creates `dating_app_test` (or "exists").

- [ ] **Step 3: Ensure asyncpg is installed** (Postgres async driver for tests):

```bash
cd /Users/junlinyi/GitHub2/da-backend && source venv/bin/activate && pip install asyncpg pytest-asyncio httpx && pip freeze | grep -E "asyncpg|pytest-asyncio|httpx"
```
Expected: all three listed.

- [ ] **Step 4: Smoke test the harness.** Create `tests/test_harness_smoke.py`:

```python
import pytest

@pytest.mark.asyncio
async def test_harness_boots(make_user, make_match, client_as):
    a = await make_user(name="Alex")
    b = await make_user(name="Mia")
    m = await make_match(a, b)
    assert m.id is not None
    async with client_as(a) as c:
        r = await c.get("/scheduling/me/upcoming-calls")
        assert r.status_code in (200, 404)  # endpoint may not exist yet
```

Run: `pytest tests/test_harness_smoke.py -v`
Expected: PASS (the assertion tolerates 404 until the endpoint exists).

- [ ] **Step 5: Delete dead tests + commit.**

```bash
cd /Users/junlinyi/GitHub2/da-backend
git rm tests/test_scheduling_integration.py tests/test_scheduling_e2e.py tests/test_scheduling_regression.py
git add tests/conftest_pg.py tests/test_harness_smoke.py seed_scheduling_audit.sql docs/
git commit -m "test(scheduling-v2): add Postgres harness, remove dead scheduling tests"
```

---

## Phase 1 — Schema (migration + ORM models)

### Task 1.1: Add V2 ORM models & columns

**Files:**
- Modify: `app/models.py` (Match `:78-104`, User `:8-75`, Message `:133-143`; add two new classes; remove 5 legacy classes `:257-333`, `:385-404`)

- [ ] **Step 1: Add new columns to `Match`** (after `user2_status`, before `scheduled_calls` relationship):

```python
    # --- Scheduling V2: three orthogonal state dimensions ---
    text_state = Column(String(20), nullable=False, default="open")       # open|locked|archived
    call_status = Column(String(30), nullable=False, default="none")      # none|proposal_pending|scheduled|in_progress|pending_survey|completed|no_show
    lifecycle = Column(String(20), nullable=False, default="active")      # active|terminated|expired
    text_locked_at = Column(DateTime(timezone=True), nullable=True)
    text_unlocked_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)           # = text_locked_at + 72h once locked
    exit_survey_user_a_response = Column(Boolean, nullable=True)
    exit_survey_user_a_responded_at = Column(DateTime(timezone=True), nullable=True)
    exit_survey_user_b_response = Column(Boolean, nullable=True)
    exit_survey_user_b_responded_at = Column(DateTime(timezone=True), nullable=True)
    contact_reveal_unlocked = Column(Boolean, nullable=False, default=False)
    contact_revealed_to_user_a_at = Column(DateTime(timezone=True), nullable=True)
    contact_revealed_to_user_b_at = Column(DateTime(timezone=True), nullable=True)
    video_call_proposals = relationship("VideoCallProposal", back_populates="match", cascade="all, delete-orphan")
    no_show_events = relationship("NoShowEvent", back_populates="match", cascade="all, delete-orphan")
```
> **Convention note:** `Match.user_id` is User A, `Match.matched_user_id` is User B. The exit-survey "user_a/user_b" columns map to these respectively. `match_state_service` resolves which column to write from the acting user's id.

- [ ] **Step 2: Add columns to `User`** (after `no_show_count`/`last_no_show_at`, `:55-57`):

```python
    total_calls_scheduled = Column(Integer, default=0, nullable=False)
    total_calls_completed = Column(Integer, default=0, nullable=False)
    phone_country_code = Column(String(8), nullable=True)
```

- [ ] **Step 3: Make `Message.sender_id` nullable + add mirror columns** (`:133-143`):

```python
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)  # NULL = system message
    has_masked_content = Column(Boolean, nullable=False, default=False)
    system_message_type = Column(String(40), nullable=True)
```

- [ ] **Step 4: Add the two new model classes** (place near `ScheduledCall`):

```python
class VideoCallProposal(Base):
    __tablename__ = "video_call_proposals"
    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, ForeignKey("matches.id", ondelete="CASCADE"), nullable=False)
    proposer_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    proposed_start_utc = Column(DateTime(timezone=True), nullable=False)
    proposed_end_utc = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # pending|accepted|superseded
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    responded_at = Column(DateTime(timezone=True), nullable=True)
    match = relationship("Match", back_populates="video_call_proposals")
    proposer = relationship("User")
    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','superseded')", name="chk_vcp_status"),
        Index("idx_one_pending_proposal_per_match", "match_id",
              unique=True, postgresql_where=text("status = 'pending'")),
        Index("idx_video_call_proposals_match", "match_id"),
    )


class NoShowEvent(Base):
    __tablename__ = "no_show_events"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    match_id = Column(Integer, ForeignKey("matches.id", ondelete="CASCADE"), nullable=False)
    scheduled_call_id = Column(Integer, ForeignKey("scheduled_calls.id", ondelete="CASCADE"), nullable=False)
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    event_type = Column(String(20), nullable=False, default="no_show")  # no_show|partial
    match = relationship("Match", back_populates="no_show_events")
    __table_args__ = (
        CheckConstraint("event_type IN ('no_show','partial')", name="chk_nse_type"),
        Index("idx_no_show_events_user_match", "user_id", "match_id"),
    )
```
Add `text` to the sqlalchemy import line (`:2`): `from sqlalchemy import ... , text`.

- [ ] **Step 5: Remove the 5 legacy model classes** — delete `SchedulingProposal` (`:257-280`), `ProposalTimeSlot` (`:283-297`), `ProposalResponse` (`:300-317`), `CounterProposalTimeSlot` (`:320-333`), `CallRequest` (`:385-404`), and any `backref`/relationship lines on `Match`/`User` pointing at them. (Keep `ScheduledCall`, `VideoCallRoom`, `CallRating`, `UserSchedulingPreferences`, `MatchOutcome`.)

- [ ] **Step 6: Verify import.** Run: `cd /Users/junlinyi/GitHub2/da-backend && source venv/bin/activate && python -c "from app import models; print('ok', models.VideoCallProposal, models.NoShowEvent)"`
Expected: `ok <class ...VideoCallProposal> <class ...NoShowEvent>` and **no** AttributeError for removed classes referenced elsewhere (fix any import errors that surface — grep `grep -rn "SchedulingProposal\|CallRequest\|ProposalTimeSlot\|ProposalResponse\|CounterProposalTimeSlot" app/` and clean).

### Task 1.2: Alembic migration

**Files:** Create `alembic/versions/<rev>_scheduling_v2.py`

- [ ] **Step 1: Autogenerate the draft.** Run:

```bash
cd /Users/junlinyi/GitHub2/da-backend && source venv/bin/activate
DATABASE_URL=postgresql://dating_user:securepassword@localhost/dating_app \
  alembic revision --autogenerate -m "scheduling_v2"
```
Expected: a new file in `alembic/versions/`, `down_revision = 'b2c3d4e5f6a7'`.

- [ ] **Step 2: Hand-fix the migration.** Autogen will miss the **partial unique index** and the legacy-table **drops** ordering and the **trigger drop**. Ensure `upgrade()` includes (in this order): add columns to `matches`/`users`/`messages`; create `video_call_proposals` + `no_show_events`; the partial unique index via raw SQL; drop trigger; drop legacy tables. Verify these statements exist (add any missing):

```python
def upgrade():
    # ... op.add_column(...) for all new matches/users/messages columns ...
    # ... op.create_table('video_call_proposals', ...) and 'no_show_events' ...
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_one_pending_proposal_per_match "
               "ON video_call_proposals (match_id) WHERE status = 'pending'")
    op.add_column('matches', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('messages', 'sender_id', existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint("chk_text_state", "matches", "text_state IN ('open','locked','archived')")
    op.create_check_constraint("chk_call_status", "matches",
        "call_status IN ('none','proposal_pending','scheduled','in_progress','pending_survey','completed','no_show')")
    op.create_check_constraint("chk_lifecycle", "matches", "lifecycle IN ('active','terminated','expired')")
    # Drop the broken trigger that references a dropped table (500s on scheduled_calls insert)
    op.execute("DROP TRIGGER IF EXISTS trigger_update_call_preferences ON scheduled_calls")
    op.execute("DROP FUNCTION IF EXISTS update_call_preferences() CASCADE")
    # Drop legacy scheduling tables (children first)
    for t in ("counter_proposal_time_slots", "proposal_responses", "proposal_time_slots",
              "scheduling_proposals", "call_requests"):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")


def downgrade():
    raise NotImplementedError("Pre-launch; forward-only V2 migration. Use seed scripts to reset.")
```
> `downgrade` is intentionally unimplemented — the spec's rollback is "revert build + reseed," and recreating dropped legacy tables is not worth the effort pre-launch.

- [ ] **Step 3: Apply against dev DB.** Run:

```bash
DATABASE_URL=postgresql://dating_user:securepassword@localhost/dating_app alembic upgrade head
```
Expected: `Running upgrade b2c3d4e5f6a7 -> <rev>, scheduling_v2`.

- [ ] **Step 4: Verify schema.** Run:

```bash
PGPASSWORD=securepassword psql -h localhost -U dating_user -d dating_app -c \
"select column_name from information_schema.columns where table_name='matches' and column_name in ('text_state','call_status','lifecycle','expires_at','contact_reveal_unlocked');
 select to_regclass('public.video_call_proposals'), to_regclass('public.no_show_events');
 select to_regclass('public.scheduling_proposals') as should_be_null;"
```
Expected: 5 match columns present, both V2 tables non-null, `scheduling_proposals` NULL.

- [ ] **Step 5: Commit.**

```bash
git add app/models.py alembic/versions/ && git commit -m "feat(scheduling-v2): schema migration + ORM models for 3-dim state machine"
```

---

## Phase 2 — Pydantic schemas

### Task 2.1: V2 schemas

**Files:** Modify `app/schemas.py` (add V2 block; remove legacy `:570-801`)

- [ ] **Step 1: Add the V2 enums + models** (near the call schemas `:431`):

```python
class TextState(str, Enum):
    OPEN = "open"; LOCKED = "locked"; ARCHIVED = "archived"

class CallLifecycleStatus(str, Enum):   # avoid clobbering existing CallStatus
    NONE = "none"; PROPOSAL_PENDING = "proposal_pending"; SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"; PENDING_SURVEY = "pending_survey"
    COMPLETED = "completed"; NO_SHOW = "no_show"

class MatchLifecycle(str, Enum):
    ACTIVE = "active"; TERMINATED = "terminated"; EXPIRED = "expired"

class ProposeCallRequest(BaseModel):
    match_id: int
    proposed_start_utc: datetime

class CounterProposalRequest(BaseModel):
    proposed_start_utc: datetime

class VideoCallProposalResponse(BaseModel):
    id: int; match_id: int; proposer_user_id: int
    proposed_start_utc: datetime; proposed_end_utc: datetime
    status: str
    class Config: from_attributes = True

class ExitSurveyRequest(BaseModel):
    response: bool

class ExitSurveyResultResponse(BaseModel):
    match_lifecycle: str; call_status: str; text_state: str; contact_reveal_unlocked: bool

class ContactResponse(BaseModel):
    peer_phone_number: Optional[str] = None
    peer_phone_country_code: Optional[str] = None

class PeerUserSummary(BaseModel):
    id: int; name: Optional[str] = None; timezone: Optional[str] = None
    no_show_count: int = 0
    class Config: from_attributes = True

class MatchListItem(BaseModel):
    match_id: int
    peer_user: PeerUserSummary
    text_state: str; call_status: str; lifecycle: str
    text_locked_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    card_display: str                      # from compute_match_card_display()
    active_proposal: Optional[VideoCallProposalResponse] = None
    scheduled_call: Optional[ScheduledCallResponse] = None
    exit_survey_self_response: Optional[bool] = None
    exit_survey_peer_response: Optional[bool] = None
    contact_reveal_unlocked: bool = False
```

- [ ] **Step 2: Remove legacy schemas** (`:570-801`): `ProposalStatus`, `ProposalResponseType`, `ProposalTimeSlotCreate/Response`, `SchedulingProposalCreate/Response`, `CounterProposalTimeSlot*`, `ProposalResponseCreate/Response`, `ProposalListResponse`, `ScheduledCallFromProposal`, `CallRequestCreate/UserInfo/Response`. Keep all `VideoCall*` schemas.

- [ ] **Step 3: Verify.** Run: `python -c "from app import schemas; print(schemas.MatchListItem.__fields__.keys())"`
Expected: prints the field set; no ImportError. Grep + fix references to removed schemas: `grep -rn "SchedulingProposalResponse\|ProposalListResponse\|CallRequestResponse\|ScheduledCallFromProposal" app/`.

- [ ] **Step 4: Commit.** `git add app/schemas.py && git commit -m "feat(scheduling-v2): V2 pydantic schemas; remove legacy proposal/call-request schemas"`

---

## Phase 3 — `match_state_service.py` (the state machine)

This phase is TDD-first against pure logic. Persistence functions are tested in Phase 4 via endpoints.

### Task 3.1: Legal-transition table + card-display (pure, unit-tested)

**Files:**
- Create: `app/services/match_state_service.py`
- Test: `tests/test_match_state_unit.py`

- [ ] **Step 1: Write failing unit tests.** `tests/test_match_state_unit.py`:

```python
import pytest
from app.services import match_state_service as mss

def test_call_status_transition_legal():
    assert mss.is_legal_call_status("none", "proposal_pending")
    assert mss.is_legal_call_status("proposal_pending", "scheduled")
    assert mss.is_legal_call_status("proposal_pending", "proposal_pending")  # counter supersede
    assert mss.is_legal_call_status("scheduled", "in_progress")
    assert mss.is_legal_call_status("in_progress", "pending_survey")
    assert mss.is_legal_call_status("pending_survey", "completed")
    assert mss.is_legal_call_status("scheduled", "no_show")
    assert mss.is_legal_call_status("no_show", "proposal_pending")  # reschedule

def test_call_status_transition_illegal():
    assert not mss.is_legal_call_status("none", "in_progress")
    assert not mss.is_legal_call_status("completed", "proposal_pending")
    assert not mss.is_legal_call_status("none", "scheduled")

@pytest.mark.parametrize("text,call,life,expected_substr", [
    ("open", "none", "active", "Texting"),
    ("open", "scheduled", "active", "Video date"),
    ("locked", "none", "active", "Schedule a video date"),
    ("locked", "proposal_pending", "active", "Review proposed time"),
    ("locked", "no_show", "active", "Missed"),
    ("open", "pending_survey", "active", "survey"),
    ("archived", "none", "expired", "expired"),
    ("archived", "none", "terminated", "ended"),
])
def test_card_display(text, call, life, expected_substr):
    s = mss.compute_match_card_display(text, call, life, hours_left=18,
                                       scheduled_start=None, is_proposer=False)
    assert expected_substr.lower() in s.lower()
```

Run: `pytest tests/test_match_state_unit.py -v`
Expected: FAIL — module/functions not defined.

- [ ] **Step 2: Implement pure logic.** `app/services/match_state_service.py` (pure section):

```python
"""Scheduling V2 match-state machine. Owns transitions of the three orthogonal
dimensions (text_state, call_status, lifecycle) and the card-display helper."""
from datetime import datetime, timedelta, timezone
from typing import Optional

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

# Legal call_status transitions (event-driven dimension).
_LEGAL_CALL_STATUS = {
    "none": {"proposal_pending"},
    "proposal_pending": {"proposal_pending", "scheduled"},  # self = counter supersede
    "scheduled": {"in_progress", "no_show", "proposal_pending"},  # reschedule re-proposes
    "in_progress": {"pending_survey", "no_show"},
    "pending_survey": {"completed"},
    "completed": set(),
    "no_show": {"proposal_pending"},
}

def is_legal_call_status(current: str, new: str) -> bool:
    return new in _LEGAL_CALL_STATUS.get(current, set())

_LEGAL_TEXT_STATE = {
    "open": {"locked", "archived"},
    "locked": {"open", "archived"},
    "archived": set(),
}

def is_legal_text_state(current: str, new: str) -> bool:
    return new in _LEGAL_TEXT_STATE.get(current, set())

def compute_match_card_display(text_state: str, call_status: str, lifecycle: str,
                               hours_left: Optional[int] = None,
                               scheduled_start: Optional[datetime] = None,
                               is_proposer: bool = False) -> str:
    if lifecycle == "expired":
        return "Match expired"
    if lifecycle == "terminated":
        return "Match ended"
    if call_status == "pending_survey":
        return "Continue texting? Complete survey"
    if call_status == "no_show":
        return "Missed — reschedule video date" if text_state == "locked" else "Texting · Reschedule video date"
    if call_status == "proposal_pending":
        if is_proposer:
            return "Waiting for response"
        return "Texting · Review proposed time" if text_state == "open" else "Review proposed time"
    if call_status in ("scheduled", "in_progress"):
        when = scheduled_start.strftime("%a %-I %p") if scheduled_start else "soon"
        prefix = "Texting · " if text_state == "open" else ""
        if call_status == "in_progress":
            return "Video date in progress"
        return f"{prefix}Video date {when}"
    if call_status == "completed":
        return "Texting · Last date complete"
    if text_state == "locked":
        return "Schedule a video date"
    # open + none
    hl = hours_left if hours_left is not None else 24
    return f"Texting · {hl}h left"
```

Run: `pytest tests/test_match_state_unit.py -v`
Expected: PASS (adjust copy strings to exactly match spec §Match-card-display column if any assertion is close-but-off).

- [ ] **Step 3: Commit.** `git add app/services/match_state_service.py tests/test_match_state_unit.py && git commit -m "feat(scheduling-v2): state-machine transition table + card-display (unit-tested)"`

### Task 3.2: Persistence transitions (DB-bound)

**Files:** Modify `app/services/match_state_service.py`

- [ ] **Step 1: Add DB transition functions** (append; these are exercised by Phase 4 integration tests):

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app import models

PROPOSAL_WINDOW_HOURS = 72
TEXT_WINDOW_HOURS = 24
DATE_DURATION_MIN = 30

async def _lock_match(db: AsyncSession, match_id: int) -> models.Match:
    res = await db.execute(
        select(models.Match).where(models.Match.id == match_id).with_for_update()
    )
    m = res.scalar_one_or_none()
    if m is None:
        raise ValueError("match_not_found")
    return m

def _is_user_a(match: models.Match, user_id: int) -> bool:
    return match.user_id == user_id

async def transition_call_status(db: AsyncSession, match_id: int, new_status: str) -> models.Match:
    m = await _lock_match(db, match_id)
    if not is_legal_call_status(m.call_status, new_status):
        raise ValueError(f"illegal_call_status:{m.call_status}->{new_status}")
    m.call_status = new_status
    await db.flush()
    return m

async def transition_text_state(db: AsyncSession, match_id: int, new_state: str) -> models.Match:
    m = await _lock_match(db, match_id)
    if not is_legal_text_state(m.text_state, new_state):
        raise ValueError(f"illegal_text_state:{m.text_state}->{new_state}")
    m.text_state = new_state
    if new_state == "locked":
        m.text_locked_at = utc_now()
        m.expires_at = m.text_locked_at + timedelta(hours=PROPOSAL_WINDOW_HOURS)
    elif new_state == "open":
        m.text_unlocked_at = utc_now()
    await db.flush()
    return m

async def process_exit_survey(db: AsyncSession, match_id: int, user_id: int, response: bool) -> models.Match:
    m = await _lock_match(db, match_id)
    if m.call_status != "pending_survey":
        raise ValueError("not_pending_survey")
    is_a = _is_user_a(m, user_id)
    already = m.exit_survey_user_a_response if is_a else m.exit_survey_user_b_response
    other = m.exit_survey_user_b_response if is_a else m.exit_survey_user_a_response
    # Immutable once BOTH responded; mutable-by-self while only self recorded.
    if already is not None and other is not None:
        raise ValueError("already_responded")
    now = utc_now()
    if is_a:
        m.exit_survey_user_a_response, m.exit_survey_user_a_responded_at = response, now
    else:
        m.exit_survey_user_b_response, m.exit_survey_user_b_responded_at = response, now
    a, b = m.exit_survey_user_a_response, m.exit_survey_user_b_response
    if a is False or b is False:
        m.lifecycle = "terminated"; m.text_state = "archived"
    elif a is True and b is True:
        m.call_status = "completed"; m.text_state = "open"
        m.text_unlocked_at = now; m.contact_reveal_unlocked = True
    await db.flush()
    return m
```

- [ ] **Step 2: Verify it imports.** Run: `python -c "from app.services import match_state_service as m; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit.** `git add app/services/match_state_service.py && git commit -m "feat(scheduling-v2): DB-bound state transitions (call/text/exit-survey) with row locks"`

---

## Phase 4 — Endpoints

Each endpoint is built test-first against the Postgres harness. Auth = `Depends(get_current_user)` → `user.id`. Participant check pattern (from `scheduling.py`): a user is a participant iff `match.user_id == user.id or match.matched_user_id == user.id`.

### Task 4.1: `POST /scheduling/calls/propose`

**Files:** Modify `app/routers/scheduling.py`; Test `tests/test_scheduling_v2_integration.py`

- [ ] **Step 1: Write failing tests:**

```python
import pytest
from app.services.match_state_service import utc_now
from datetime import timedelta

@pytest.mark.asyncio
async def test_propose_happy_path(make_user, make_match, client_as, db):
    a = await make_user(name="Alex"); b = await make_user(name="Mia")
    m = await make_match(a, b)  # defaults: open/none/active
    start = (utc_now() + timedelta(hours=5)).isoformat()
    async with client_as(a) as c:
        r = await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": start})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending" and body["proposer_user_id"] == a.id
    await db.refresh(m); assert m.call_status == "proposal_pending"

@pytest.mark.asyncio
async def test_propose_past_time_400(make_user, make_match, client_as):
    a = await make_user(name="A"); b = await make_user(name="B"); m = await make_match(a, b)
    past = (utc_now() - timedelta(hours=1)).isoformat()
    async with client_as(a) as c:
        r = await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": past})
    assert r.status_code == 400

@pytest.mark.asyncio
async def test_propose_beyond_72h_400(make_user, make_match, client_as):
    a = await make_user(name="A"); b = await make_user(name="B"); m = await make_match(a, b)
    far = (utc_now() + timedelta(hours=80)).isoformat()
    async with client_as(a) as c:
        r = await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": far})
    assert r.status_code == 400

@pytest.mark.asyncio
async def test_propose_conflict_returns_active(make_user, make_match, client_as):
    a = await make_user(name="A"); b = await make_user(name="B"); m = await make_match(a, b)
    s1 = (utc_now() + timedelta(hours=5)).isoformat()
    s2 = (utc_now() + timedelta(hours=6)).isoformat()
    async with client_as(a) as c:
        await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": s1})
    async with client_as(b) as c:
        r = await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": s2})
    assert r.status_code == 409
    assert "proposed_start_utc" in r.json()["detail"] or r.json().get("active_proposal")
```

Run: `pytest tests/test_scheduling_v2_integration.py -k propose -v`  → FAIL (404, no endpoint).

- [ ] **Step 2: Implement.** In `app/routers/scheduling.py` add:

```python
from app.services import match_state_service as mss
from app import schemas, models

@router.post("/calls/propose", response_model=schemas.VideoCallProposalResponse)
async def propose_call(body: schemas.ProposeCallRequest,
                       user: models.User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    start = body.proposed_start_utc
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    now = mss.utc_now()
    if start <= now:
        raise HTTPException(400, "Proposed time is in the past")
    if start > now + timedelta(hours=mss.PROPOSAL_WINDOW_HOURS):
        raise HTTPException(400, "Proposed time is more than 72 hours ahead")
    m = await mss._lock_match(db, body.match_id)
    if user.id not in (m.user_id, m.matched_user_id):
        raise HTTPException(403, "Not a match participant")
    if m.lifecycle != "active" or m.text_state == "archived":
        raise HTTPException(409, "Match not in a schedulable state")
    # one-pending-proposal guard
    existing = (await db.execute(
        select(models.VideoCallProposal).where(
            models.VideoCallProposal.match_id == m.id,
            models.VideoCallProposal.status == "pending"))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, detail={"message": "A proposal is already pending",
            "active_proposal": schemas.VideoCallProposalResponse.model_validate(existing).model_dump(mode="json")})
    prop = models.VideoCallProposal(
        match_id=m.id, proposer_user_id=user.id,
        proposed_start_utc=start, proposed_end_utc=start + timedelta(minutes=mss.DATE_DURATION_MIN),
        status="pending")
    db.add(prop)
    if mss.is_legal_call_status(m.call_status, "proposal_pending"):
        m.call_status = "proposal_pending"
    await db.commit(); await db.refresh(prop)
    # push to the non-proposer (best-effort)
    await _notify_proposal_received(db, m, proposer=user)
    return prop
```
Add imports at top of router if missing: `from datetime import timedelta, timezone`, `from sqlalchemy import select`, `from fastapi import HTTPException`. Define a thin `_notify_proposal_received` helper that resolves the peer `User` and calls `push.notify_proposal_received` (Phase 7 wires the real copy; for now it can call the existing function).

- [ ] **Step 3:** Run `pytest tests/test_scheduling_v2_integration.py -k propose -v` → PASS.
- [ ] **Step 4: Commit.** `git commit -am "feat(scheduling-v2): POST /scheduling/calls/propose + tests"`

### Task 4.2: `POST /scheduling/calls/{proposal_id}/accept`

- [ ] **Step 1: Tests** (accept happy path → creates `ScheduledCall` 30-min, sets `call_status=scheduled`, proposal `accepted`, increments both users' `total_calls_scheduled`; 403 if proposer accepts own; 409 if not pending):

```python
@pytest.mark.asyncio
async def test_accept_creates_scheduled_call(make_user, make_match, client_as, db):
    a = await make_user(name="A"); b = await make_user(name="B"); m = await make_match(a, b)
    start = (utc_now() + timedelta(hours=5)).isoformat()
    async with client_as(a) as c:
        pid = (await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": start})).json()["id"]
    async with client_as(b) as c:
        r = await c.post(f"/scheduling/calls/{pid}/accept")
    assert r.status_code == 200
    await db.refresh(m); assert m.call_status == "scheduled"
    call = r.json(); assert call["duration_minutes"] == 30

@pytest.mark.asyncio
async def test_proposer_cannot_accept_own(make_user, make_match, client_as):
    a = await make_user(name="A"); b = await make_user(name="B"); m = await make_match(a, b)
    start = (utc_now() + timedelta(hours=5)).isoformat()
    async with client_as(a) as c:
        pid = (await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": start})).json()["id"]
        r = await c.post(f"/scheduling/calls/{pid}/accept")
    assert r.status_code == 403
```

Run → FAIL.

- [ ] **Step 2: Implement** `@router.post("/calls/{proposal_id}/accept", response_model=schemas.ScheduledCallResponse)`:
  - lock proposal; 404 if missing; 409 if `status != "pending"`.
  - lock match; 403 if `user.id not in participants`; 403 if `user.id == proposal.proposer_user_id`.
  - set `proposal.status = "accepted"`, `proposal.responded_at = now`.
  - create `models.ScheduledCall(match_id, user1_id=m.user_id, user2_id=m.matched_user_id, scheduled_start_utc=proposal.proposed_start_utc, scheduled_end_utc=proposal.proposed_end_utc, duration_minutes=30, status="scheduled")`.
  - `m.call_status = "scheduled"`.
  - `a.total_calls_scheduled += 1; b.total_calls_scheduled += 1` (load both Users).
  - commit; build `ScheduledCallResponse` exactly like legacy `schedule_call` does (populate `start_time_utc`/`end_time_utc` strings + `other_user_*`). Reference `scheduling.py:291` for the response-construction pattern.
  - push `notify_proposal_accepted(proposer, accepter, call_id)`.
- [ ] **Step 3:** Run → PASS. **Step 4: Commit.**

### Task 4.3: `POST /scheduling/calls/{proposal_id}/counter`

- [ ] **Step 1: Tests** (counter by non-proposer supersedes prior → old `superseded`, new `pending`, `call_status` stays `proposal_pending`; 409/403 if the *proposer* tries to counter their own active proposal; verification: spec Test 3 expects N superseded + 1 accepted).
- [ ] **Step 2: Implement** `@router.post("/calls/{proposal_id}/counter", response_model=schemas.VideoCallProposalResponse)`:
  - validate time (past / >72h) like propose.
  - lock proposal + match; 403 if not participant; **403 if `user.id == proposal.proposer_user_id`** (only the non-proposer may counter the active proposal).
  - `proposal.status = "superseded"`; insert new `pending` proposal with `proposer_user_id = user.id`.
  - `call_status` stays `proposal_pending`.
  - push `notify_counter_proposal_received`.
- [ ] **Step 3:** PASS. **Step 4: Commit.**

### Task 4.4: `GET /scheduling/me/matches` (rewrite)

- [ ] **Step 1: Tests** — returns one `MatchListItem` per active match for the user, with correct `text_state/call_status/lifecycle`, `card_display`, `active_proposal` when pending, `scheduled_call` when scheduled, `peer_user.no_show_count`, and `exit_survey_self/peer_response`. Test the concurrent state `(open, scheduled, active)` → `card_display` contains "Texting" and "Video date".
- [ ] **Step 2: Implement** — replace the legacy `get_my_matches_without_calls` (`scheduling.py:212`). Query matches where user is participant AND `lifecycle = 'active'`. For each, resolve peer User, latest pending proposal, latest scheduled call, compute `hours_left` from `created_at + 24h` (if `text_state='open'`) or from `expires_at`, call `mss.compute_match_card_display(...)`. Map self/peer exit-survey responses by `_is_user_a`. Return `List[MatchListItem]`.
- [ ] **Step 3:** PASS. **Step 4: Commit.**

### Task 4.5: `GET /scheduling/me/upcoming-calls`

- [ ] **Step 1: Tests** — returns the user's future `ScheduledCall`s with `status='scheduled'` and `scheduled_start_utc > now`, as `ScheduledCallResponse[]`.
- [ ] **Step 2: Implement** `@router.get("/me/upcoming-calls", response_model=List[schemas.ScheduledCallResponse])`. Reuse the response-shaping from `get_my_calls` (`scheduling.py:122`).
- [ ] **Step 3:** PASS. **Step 4: Commit.**

### Task 4.6: `POST /scheduling/calls/{call_id}/no-show` (cron-facing)

- [ ] **Step 1: Tests** — given a `scheduled` call past `start + 10min` with `<2` joiners, marks call `no_show`, writes one `NoShowEvent` per non-joiner, increments each non-joiner's `users.no_show_count`, sets `match.call_status='no_show'`. Second no-show by same user on same match → `lifecycle='terminated'`, `text_state='archived'`. Returns `{no_show_count, match_terminated}`. 409 if not yet past grace.
- [ ] **Step 2: Implement** the endpoint as a thin wrapper over `mss.record_no_show(db, call_id, no_show_user_ids)` (add that function to the service — see Phase 6 cron, which calls the same core). Determine non-joiners from `ScheduledCall.user1_confirmed`/`call_started_at`/join signals (legacy uses confirmations; for V2 a joiner is one who hit `/video-calls/rooms` for the call — track via `VideoCallRoom`/a `joined` flag; if no join signal exists, treat both unconfirmed as no-show).
- [ ] **Step 3:** PASS. **Step 4: Commit.**

> **Join-signal note:** the cleanest join signal is a new boolean pair on `ScheduledCall` (`user1_joined`, `user2_joined`) set when `/video-calls/{id}/start` is called (Task 8.1). If you prefer not to add columns, derive "joined" from a `VideoCallRoom` participant log. Pick one in Task 8.1 and keep `record_no_show` consistent with it.

### Task 4.7: `/matches/{match_id}` survey + contact endpoints

Add these under the scheduling router (path `/matches/...`) or a small new `app/routers/matches.py` mounted at `/matches`. (Confirm no existing `/matches` router collides: `grep -rn 'prefix="/matches"' app/`.)

- [ ] **Step 1: Tests:**
  - `POST /matches/{id}/exit-survey {response:true}` when `call_status='pending_survey'` → writes self response; both true → `call_status='completed'`, `text_state='open'`, `contact_reveal_unlocked=true`. Returns `ExitSurveyResultResponse`. 400 if not `pending_survey`; 409 if already responded (both in).
  - `GET /matches/{id}/contact` → 403 unless `contact_reveal_unlocked`; else returns peer `phone_number` + `phone_country_code`.
  - `POST /matches/{id}/reveal-contact` → stamps `contact_revealed_to_user_{a|b}_at`; 403 if not unlocked.
- [ ] **Step 2: Implement** using `mss.process_exit_survey`. For contact, resolve peer and read `phone_number`/`phone_country_code`. Fire `notify_text_unlocked_mutual_yes` / `notify_partner_responded_yes` / `notify_match_terminated_survey_no` based on the returned state delta.
- [ ] **Step 3:** PASS. **Step 4: Commit.**

---

## Phase 5 — Messaging text-gate + mask + system messages

### Task 5.1: `chat_message_filter.py` stub

- [ ] **Step 1: Test** `tests/test_chat_filter_unit.py`:

```python
from app.services.chat_message_filter import filter_message_content
import pytest

@pytest.mark.parametrize("raw", ["call me 555-123-4567", "555.123.4567", "(555) 123 4567"])
def test_masks_phone(raw):
    filtered, masked = filter_message_content(raw)
    assert masked is True and "[phone hidden]" in filtered

def test_clean_passthrough():
    filtered, masked = filter_message_content("hey how are you")
    assert masked is False and filtered == "hey how are you"
```

- [ ] **Step 2: Implement** `app/services/chat_message_filter.py`:

```python
import re
_PHONE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
def filter_message_content(content: str) -> tuple[str, bool]:
    """V1 stub — full algorithm deferred to the moderation spec."""
    if _PHONE.search(content):
        return _PHONE.sub("[phone hidden]", content), True
    return content, False
```
- [ ] **Step 3:** PASS. **Step 4: Commit.**

### Task 5.2: Gate `send_message` on text_state + apply mask

**Files:** Modify `app/routers/messaging.py` `send_message` (`:233`)

- [ ] **Step 1: Test** (integration; messaging uses `verify_firebase_token` + Firestore — for the test, override `verify_firebase_token` too and stub the Firestore writer). At minimum, unit-test the new guard helper `assert_text_open(match)` raising 403 when locked, and test that masking is applied to mirrored content. Add `tests/test_messaging_gate.py`:

```python
import pytest
from app.routers.messaging import _resolve_match_for_conversation, assert_text_open
from app import models

def test_assert_text_open_blocks_locked():
    m = models.Match(text_state="locked")
    with pytest.raises(Exception):
        assert_text_open(m)

def test_assert_text_open_allows_open():
    m = models.Match(text_state="open")
    assert_text_open(m) is None
```

- [ ] **Step 2: Implement** in `messaging.py`:
  - Add `def assert_text_open(match): if match.text_state != "open": raise HTTPException(403, "Text is locked — schedule a video date")`.
  - In `send_message`: resolve the backing `Match` for the Firestore `conversation_id` (map conversation→match; if conversation id ≠ match id, add a lookup — conversations carry `user1_id/user2_id`, match the pair). Call `assert_text_open(match)` before writing.
  - Run `content, masked = filter_message_content(message.content)`; write the (masked) content to Firestore and the mirror; set `Message.has_masked_content = masked`.
- [ ] **Step 3:** PASS. **Step 4: Commit.**

### Task 5.3: System-message writer

- [ ] **Step 1:** Add `app/services/match_state_service.py: async def write_system_message(db, match, system_message_type, text)` that (a) writes a Firestore message doc `{senderId: None, content: text, messageType: "system", systemMessageType: type, timestamp}` into the match's conversation subcollection (reuse the Firestore client/path from `messaging.py`), and (b) mirrors a `models.Message(sender_id=None, content=text, message_type="system", system_message_type=type)` row.
- [ ] **Step 2:** Call `write_system_message` from: propose (`proposal_created`, only when `text_state='open'` per spec Flow 2 step 5), accept (`call_scheduled`), counter (`proposal_countered`), text-lock cron (`text_locked`), exit-survey unlock (`text_unlocked`), no-show (`call_no_show`).
- [ ] **Step 3: Test** that calling propose with `text_state='open'` produces a mirrored system Message row with `system_message_type='proposal_created'` and `sender_id IS NULL`; with `text_state='locked'` it does **not** (spec Flow 2 step 5). **Step 4: Commit.**

---

## Phase 6 — Crons

### Task 6.1: `lock_text_for_eligible_matches` (60s loop)

**Files:** Modify `app/services/scheduling_monitor_service.py`, `app/main.py`; add functions to `match_state_service.py`; Test `tests/test_scheduling_v2_crons.py`

- [ ] **Step 1: Test** — a match with `text_state='open'`, `lifecycle='active'`, `created_at = now-25h` gets locked (`text_state='locked'`, `text_locked_at` set, `expires_at = locked+72h`); a match `created_at = now-1h` is untouched; locking fires `text_locked` push only when `call_status='none'`.

```python
@pytest.mark.asyncio
async def test_lock_text_after_24h(make_user, make_match, db):
    from app.services import match_state_service as mss
    a = await make_user(name="A"); b = await make_user(name="B")
    old = await make_match(a, b); old.created_at = mss.utc_now() - timedelta(hours=25)
    fresh = await make_match(a, b); fresh.created_at = mss.utc_now() - timedelta(hours=1)
    await db.commit()
    n = await mss.lock_text_for_eligible_matches(db)
    await db.refresh(old); await db.refresh(fresh)
    assert old.text_state == "locked" and old.text_locked_at is not None and old.expires_at is not None
    assert fresh.text_state == "open"
```

- [ ] **Step 2: Implement** `mss.lock_text_for_eligible_matches(db)`:
  - `select` matches where `text_state='open' AND lifecycle='active' AND created_at < now-24h`.
  - for each: set `text_state='locked'`, `text_locked_at=now`, `expires_at=now+72h`; if `call_status='none'` fire `text_locked` push + `write_system_message(..., 'text_locked', ...)`.
  - return count.
  - Add nudge functions `notify_text_window_remaining(db)` (5h + 1h before lock = at 19h/23h elapsed, only if `call_status='none'`).
- [ ] **Step 3: Wire the 60s loop.** In `scheduling_monitor_service.py` add `async def fast_loop(self)` running `lock_text_for_eligible_matches` + nudges every 60s; in `main.py` startup `asyncio.create_task(scheduling_monitor.fast_loop())`. Keep the existing 300s loop for expiry/no-show.
- [ ] **Step 4:** Run cron test → PASS. **Step 5: Commit.**

### Task 6.2: `expire_unscheduled_matches` (300s loop)

- [ ] **Step 1: Test** — match `text_state='locked'`, `lifecycle='active'`, `call_status IN ('none','no_show')`, `text_locked_at = now-73h` → `lifecycle='expired'`, `text_state='archived'`, `match_expired_unscheduled` push. A match with `call_status='scheduled'` is **protected** (not expired).
- [ ] **Step 2: Implement** `mss.expire_unscheduled_matches(db)` per spec §Service Logic. Replace the legacy `expire_stale_matches` call in `check_all_matches` with this.
- [ ] **Step 3:** PASS. **Step 4: Commit.**

### Task 6.3: `detect_no_shows` (300s loop) + `record_no_show`

- [ ] **Step 1: Test** (mirror Task 4.6 tests at the cron level — single no-show → `no_show` + 1 event; both → 2 events; second event same user/match → terminate). Grace = **10 min** (spec), not legacy 20.
- [ ] **Step 2: Implement** `mss.detect_no_shows(db)` → finds `scheduled` calls past `start+10min` with `<2` joined, calls `mss.record_no_show(db, call, non_joiner_ids)` which: sets call `status='no_show'`, `match.call_status='no_show'`, inserts a `NoShowEvent` per non-joiner, increments `users.no_show_count`+`last_no_show_at`, then if any user has `>=2` events on this match → `lifecycle='terminated'`, `text_state='archived'` + `match_terminated_no_show` push; else `date_no_show_reschedule` push. Replace legacy `detect_no_shows` in `check_all_matches`.
- [ ] **Step 3:** PASS. **Step 4: Commit.**

---

## Phase 7 — Push notifications

### Task 7.1: Add the 16 V2 typed senders

**Files:** Modify `app/services/push_notification_service.py` (follow the exact pattern at `:85-266`: `async def notify_x(recipient_user, ...ctx): if not _push_enabled(recipient): return; await send_push(token=recipient.device_token, title=..., body=..., data={...})`).

- [ ] **Step 1: Test** `tests/test_push_v2.py` — monkeypatch `send_push` to record calls; assert each notifier builds the spec copy (use the exact templates from SCHEDULING_V2 §Push Notifications). Example:

```python
@pytest.mark.asyncio
async def test_proposal_received_copy(monkeypatch):
    from app.services import push_notification_service as p
    sent = {}
    async def fake(**kw): sent.update(kw); return True
    monkeypatch.setattr(p, "send_push", fake)
    class U: device_token="t"; scheduling_preferences=None
    await p.notify_proposal_received_v2(U(), proposer_name="Junlin", when_text="Thursday 8:00 PM")
    assert "Junlin" in sent["body"] and "video date" in sent["body"].lower()
```

- [ ] **Step 2: Implement** all 16, copy verbatim from the spec table (IDs: `text_window_5h_remaining`, `text_window_locking`, `text_locked`, `proposal_received`, `proposal_accepted`, `counter_proposal_received`, `match_expiring_soon`, `date_starting_soon`, `date_starting_now`, `date_no_show_reschedule`, `match_terminated_no_show`, `match_expired_unscheduled`, `exit_survey_prompt`, `partner_responded_yes`, `text_unlocked_mutual_yes`, `match_terminated_survey_no`). Each `data={"type": "<id>", "match_id": ..., ...}` so iOS `NotificationRouter` can route. **All user-facing copy says "video date," never "video call."**
- [ ] **Step 3: Remove legacy senders** no longer referenced (`notify_immediate_call_request`, `notify_proposal_rejected`, `notify_availability_match`) after confirming no call sites remain (`grep -rn notify_immediate_call_request app/`).
- [ ] **Step 4:** PASS. **Step 5: Commit.**

### Task 7.2: Wire `date_starting_soon`/`date_starting_now` into the cron

- [ ] Add to the 300s loop: find `scheduled` calls 15 min out → `date_starting_soon`; at start → `date_starting_now`. Use existing `ScheduledCall.reminder_sent` to dedupe. Test + commit.

---

## Phase 8 — Twilio call lifecycle hooks

### Task 8.1: `in_progress` on join

- [ ] **Step 1: Decide the join signal** (per Task 4.6 note). Recommended: add `user1_joined`/`user2_joined` booleans to `ScheduledCall` (small migration `op.add_column`), set when `/video-calls/rooms` is hit for that call. When both joined → `mss.transition_call_status(db, match_id, "in_progress")` + `users.total_calls_completed += 1` for each (per spec: "increments when both users join").
- [ ] **Step 2: Test** both-joined → `call_status='in_progress'`, both `total_calls_completed` incremented. Commit.

### Task 8.2: `pending_survey` on call end

- [ ] **Step 1:** In `video_calls.py: end_call` (`:254`), after setting `ScheduledCall.status`, if ended normally: `mss.transition_call_status(db, match_id, "pending_survey")` and fire `exit_survey_prompt` push to both + `write_system_message('exit_survey_prompt'...)`. (For E2E without two real video clients, also expose `POST /video-calls/{id}/debug-end` guarded behind a debug flag that calls the same path — for manual sim testing.)
- [ ] **Step 2: Test** end_call → `call_status='pending_survey'`, survey push fired. Commit.

---

## Phase 9 — Cleanup, seed, legacy removal

### Task 9.1: Remove legacy endpoints

- [ ] Delete from `scheduling.py`: `create_scheduling_proposal` (`:534`), `get_user_proposals` (`:652`), `get_proposal` (`:721`), `respond_to_proposal` (`:777`), all `/call-requests*` (`:1011-1270`). Delete the legacy `extend_call` if it referenced the 48h model. Run `grep -rn "proposals\|call-requests" app/routers/` to confirm none remain. Build-check: `python -c "import app.main"`. Commit.

### Task 9.2: V2 seed script

- [ ] Create `seed_scheduling_v2.sql` (idempotent, single BEGIN/COMMIT) that, for matches **57 (Alex 87 ↔ Mia 85)** and **60 (Jordan 89 ↔ Riley 90)**: sets `status='accepted'`, `user1_status/user2_status='active'`, `deleted_at=NULL`, `text_state='open'`, `call_status='none'`, `lifecycle='active'`, `text_locked_at=NULL`, `expires_at=NULL`, `created_at=NOW()`, and clears any `video_call_proposals`/`scheduled_calls`/exit-survey columns for a clean `(open,none,active)` start. (If users 85/87/89/90 don't exist in dev, seed them first or pick existing pairs — verify with `psql -c "select id,name from users where id in (85,87,89,90)"`.) Test: run it, then `GET /scheduling/me/matches` as Alex returns match 57 in `(open,none,active)`. Commit.

### Task 9.3: Full backend test sweep

- [ ] Run `pytest tests/ -v` → all green. Run `python -c "import app.main"` → no import errors. Start the server (`uvicorn app.main:app --port 8001`) and hit `/docs` → confirm V2 endpoints listed, legacy gone. Commit a WORK_LOG entry.

---

## Phase 10 — Backend E2E (manual, against running server)

Drives the spec's backend E2E with `curl` + verification SQL (no iOS yet). For each, use a script that mints/loads a Firebase token for Alex/Mia or temporarily overrides auth in a dev-only header.

- [ ] **E2E-B1 Propose→Accept (Flow 1):** propose as Alex → `call_status='proposal_pending'` + system msg row; accept as Mia → `ScheduledCall` row (30 min), `call_status='scheduled'`, both `total_calls_scheduled=1`. SQL: `SELECT text_state,call_status,lifecycle FROM matches WHERE id=57` → `open|scheduled|active`.
- [ ] **E2E-B2 Counter (Flow 3):** propose→counter→counter→accept → `video_call_proposals` shows N `superseded` + 1 `accepted`.
- [ ] **E2E-B3 Text lock:** set `created_at=now-25h`, run `lock_text_for_eligible_matches` → `text_state='locked'`, `expires_at` set; `POST send_message` → 403.
- [ ] **E2E-B4 Expiration (Flow 4):** `text_locked_at=now-73h`, `call_status='none'` → `expire_unscheduled_matches` → `expired|archived`.
- [ ] **E2E-B5 No-show ×2 (Flow 5):** schedule, advance past grace twice → 2 `no_show_events`, `lifecycle='terminated'`.
- [ ] **E2E-B6 Exit survey:** end call → `pending_survey`; both yes → `completed`, `text_state='open'`, `contact_reveal_unlocked=true`; `GET /matches/57/contact` → peer phone.
- [ ] **E2E-B7 Race (Flow 6):** two near-simultaneous proposes → second gets 409 + active proposal payload.
- [ ] Run the spec's §Test Plan "Verification queries" (orphans=0, no `locked` w/ null `text_locked_at`, no_show aggregate==events). Commit results to WORK_LOG.

---

## Self-Review checklist (run before handing to iOS)

- [ ] Every spec §Endpoints row maps to a task (propose/accept/counter/me-matches/me-upcoming/no-show/send-message/exit-survey/contact/reveal-contact). ✔ Tasks 4.1–4.7, 5.2.
- [ ] Every spec §Schema row exists in the migration (3 dims, timing, survey, contact, `video_call_proposals`, `no_show_events`, users counters, messages cols, legacy drops). ✔ Task 1.
- [ ] Every cron (lock/expire/no-show + nudges + date reminders) has a task + test. ✔ Phase 6, 7.2.
- [ ] All 16 notification IDs implemented with verbatim copy + `data.type` for routing. ✔ Task 7.1.
- [ ] Naming consistency: `call_status` values, `text_state` values, `lifecycle` values identical across models/schemas/service/tests. ✔
- [ ] No `video_call`-vs-`video date` copy leaks in user-facing strings. ✔ (push + system messages).
- [ ] Twilio reused, not rebuilt; `total_calls_completed` increments on join, `total_calls_scheduled` on accept. ✔ Tasks 4.2, 8.1.

## Execution handoff

After this plan is approved, execute via **superpowers:subagent-driven-development** (fresh subagent per task, two-stage review) — recommended for a build this size — or **superpowers:executing-plans** (inline, batched checkpoints). Backend must reach Phase 9 green before the iOS plan's wiring phases begin.
