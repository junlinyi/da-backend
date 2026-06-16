"""Phase 8 (Tasks 8.1 + 8.2) — V2 call-status lifecycle hooks on the existing
Twilio video endpoints.

Runs against the Postgres test harness (tests/conftest_pg.py).

Twilio: `create_or_get_video_call_room` ("/rooms", the join hook) touches NO
Twilio API. `end_call` ("/{call_id}/end") only calls Twilio when an *active*
VideoCallRoom row exists; we monkeypatch `get_twilio_client` in
`app.routers.video_calls` so the endpoint runs without real Twilio. The exit
survey push (`notify_exit_survey_prompt`) is monkeypatched to a no-op recorder.
"""
import pytest
from datetime import timedelta

from sqlalchemy import select

from app import models
from app.routers import video_calls as vc
from app.services.match_state_service import utc_now


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_call(db, match, user1, user2, **overrides):
    start = utc_now()
    kwargs = dict(
        match_id=match.id,
        user1_id=user1.id,
        user2_id=user2.id,
        scheduled_start_utc=start,
        scheduled_end_utc=start + timedelta(minutes=30),
        duration_minutes=30,
        status="scheduled",
    )
    kwargs.update(overrides)
    call = models.ScheduledCall(**kwargs)
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return call


class _FakeTwilio:
    """Stand-in for the Twilio Client; records room close calls."""
    def __init__(self):
        self.closed = []

        class _Rooms:
            def __init__(self, outer):
                self._outer = outer

            def __call__(self, room_name):
                self._room_name = room_name
                return self

            def update(self, status):
                self._outer.closed.append((self._room_name, status))
                return None

        class _V1:
            def __init__(self, outer):
                self.rooms = _Rooms(outer)

        class _Video:
            def __init__(self, outer):
                self.v1 = _V1(outer)

        self.video = _Video(self)


@pytest.fixture(autouse=True)
def _mock_twilio_and_push(monkeypatch):
    monkeypatch.setattr(vc, "get_twilio_client", lambda: _FakeTwilio())

    sent = []

    async def _fake_prompt(recipient, peer_name, match_id):
        sent.append((getattr(recipient, "id", None), peer_name, match_id))

    monkeypatch.setattr(vc.push, "notify_exit_survey_prompt", _fake_prompt)
    return sent


# ---------------------------------------------------------------------------
# Task 8.1 — in_progress on join + total_calls_completed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_both_join_transitions_in_progress(make_user, make_match, client_as, db):
    a = await make_user(name="Alex")
    b = await make_user(name="Mia")
    m = await make_match(a, b, call_status="scheduled")
    call = await _make_call(db, m, a, b)

    # User A joins -> only one joined, still scheduled.
    async with client_as(a) as c:
        r = await c.post("/video-calls/rooms", json={"call_id": call.id})
    assert r.status_code == 200, r.text
    await db.refresh(call); await db.refresh(m)
    assert call.user1_joined is True
    assert call.user2_joined is False
    assert m.call_status == "scheduled"

    # User B joins -> both present -> in_progress.
    async with client_as(b) as c:
        r = await c.post("/video-calls/rooms", json={"call_id": call.id})
    assert r.status_code == 200, r.text
    await db.refresh(call); await db.refresh(m); await db.refresh(a); await db.refresh(b)
    assert call.user2_joined is True
    assert m.call_status == "in_progress"
    assert call.status == "in_progress"
    assert call.call_started_at is not None
    assert a.total_calls_completed == 1
    assert b.total_calls_completed == 1


@pytest.mark.asyncio
async def test_rejoin_does_not_double_count(make_user, make_match, client_as, db):
    a = await make_user(name="Alex")
    b = await make_user(name="Mia")
    m = await make_match(a, b, call_status="scheduled")
    call = await _make_call(db, m, a, b)

    async with client_as(a) as c:
        await c.post("/video-calls/rooms", json={"call_id": call.id})
    async with client_as(b) as c:
        await c.post("/video-calls/rooms", json={"call_id": call.id})

    await db.refresh(a); await db.refresh(b); await db.refresh(m)
    assert m.call_status == "in_progress"
    assert a.total_calls_completed == 1
    assert b.total_calls_completed == 1

    # A re-joins an already in-progress call -> no double count, still in_progress.
    async with client_as(a) as c:
        r = await c.post("/video-calls/rooms", json={"call_id": call.id})
    assert r.status_code == 200, r.text
    await db.refresh(a); await db.refresh(b); await db.refresh(m)
    assert a.total_calls_completed == 1
    assert b.total_calls_completed == 1
    assert m.call_status == "in_progress"


# ---------------------------------------------------------------------------
# Task 8.2 — pending_survey on call end + exit_survey_prompt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_end_call_transitions_pending_survey(make_user, make_match, client_as, db,
                                                   _mock_twilio_and_push):
    a = await make_user(name="Alex")
    b = await make_user(name="Mia")
    m = await make_match(a, b, call_status="in_progress")
    call = await _make_call(db, m, a, b, status="in_progress",
                            user1_joined=True, user2_joined=True)

    async with client_as(a) as c:
        r = await c.post(f"/video-calls/{call.id}/end",
                         json={"ended_reason": "completed", "actual_duration_minutes": 28})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"

    await db.refresh(m); await db.refresh(call)
    assert m.call_status == "pending_survey"
    assert call.status == "completed"
    # Exit survey prompt fired to both participants.
    sent = _mock_twilio_and_push
    assert len(sent) == 2
    assert {uid for uid, _, _ in sent} == {a.id, b.id}


@pytest.mark.asyncio
async def test_end_call_no_show_reason_no_survey(make_user, make_match, client_as, db,
                                                 _mock_twilio_and_push):
    a = await make_user(name="Alex")
    b = await make_user(name="Mia")
    m = await make_match(a, b, call_status="in_progress")
    call = await _make_call(db, m, a, b, status="in_progress",
                            user1_joined=True, user2_joined=True)

    async with client_as(a) as c:
        r = await c.post(f"/video-calls/{call.id}/end",
                         json={"ended_reason": "no_show"})
    assert r.status_code == 200, r.text

    await db.refresh(m); await db.refresh(call)
    assert m.call_status != "pending_survey"
    assert m.call_status == "in_progress"  # left to the no-show flow
    assert call.status == "no_show"
    assert len(_mock_twilio_and_push) == 0


@pytest.mark.asyncio
async def test_end_call_cancelled_reason_no_survey(make_user, make_match, client_as, db,
                                                   _mock_twilio_and_push):
    a = await make_user(name="Alex")
    b = await make_user(name="Mia")
    m = await make_match(a, b, call_status="in_progress")
    call = await _make_call(db, m, a, b, status="in_progress",
                            user1_joined=True, user2_joined=True)

    async with client_as(a) as c:
        r = await c.post(f"/video-calls/{call.id}/end",
                         json={"ended_reason": "cancelled"})
    assert r.status_code == 200, r.text

    await db.refresh(m); await db.refresh(call)
    assert m.call_status == "in_progress"
    assert call.status == "cancelled"
    assert len(_mock_twilio_and_push) == 0


# ---------------------------------------------------------------------------
# Debug E2E driver
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_debug_advance_join_and_end(make_user, make_match, client_as, db,
                                          _mock_twilio_and_push, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    a = await make_user(name="Alex")
    b = await make_user(name="Mia")
    m = await make_match(a, b, call_status="scheduled")
    call = await _make_call(db, m, a, b)

    async with client_as(a) as c:
        r = await c.post(f"/video-calls/{call.id}/debug-advance",
                         json={"action": "join_both"})
    assert r.status_code == 200, r.text
    await db.refresh(m); await db.refresh(call); await db.refresh(a); await db.refresh(b)
    assert m.call_status == "in_progress"
    assert call.user1_joined and call.user2_joined
    assert a.total_calls_completed == 1
    assert b.total_calls_completed == 1

    async with client_as(a) as c:
        r = await c.post(f"/video-calls/{call.id}/debug-advance",
                         json={"action": "end"})
    assert r.status_code == 200, r.text
    await db.refresh(m); await db.refresh(call)
    assert m.call_status == "pending_survey"
    assert call.status == "completed"
    assert len(_mock_twilio_and_push) == 2


@pytest.mark.asyncio
async def test_debug_advance_blocked_in_production(make_user, make_match, client_as, db,
                                                   monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("ENABLE_DEBUG_ENDPOINTS", raising=False)
    a = await make_user(name="Alex")
    b = await make_user(name="Mia")
    m = await make_match(a, b, call_status="scheduled")
    call = await _make_call(db, m, a, b)

    async with client_as(a) as c:
        r = await c.post(f"/video-calls/{call.id}/debug-advance",
                         json={"action": "join_both"})
    assert r.status_code == 404, r.text
