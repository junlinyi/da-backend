"""Integration tests for Scheduling V2 proposal-lifecycle endpoints
(Tasks 4.1–4.3): propose / accept / counter.

Run against the Postgres test harness (tests/conftest_pg.py) so the partial
unique index on video_call_proposals (one 'pending' per match) behaves exactly
as production.
"""
import pytest
from datetime import timedelta

from app.services.match_state_service import utc_now


# ---------------------------------------------------------------------------
# Task 4.1 — POST /scheduling/calls/propose
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_propose_happy_path(make_user, make_match, client_as, db):
    a = await make_user(name="Alex"); b = await make_user(name="Mia")
    m = await make_match(a, b)
    start = (utc_now() + timedelta(hours=5)).isoformat()
    async with client_as(a) as c:
        r = await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": start})
    assert r.status_code == 200, r.text
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
async def test_propose_non_participant_403(make_user, make_match, client_as):
    a = await make_user(name="A"); b = await make_user(name="B"); c2 = await make_user(name="C")
    m = await make_match(a, b)
    start = (utc_now() + timedelta(hours=5)).isoformat()
    async with client_as(c2) as c:
        r = await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": start})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_propose_conflict_returns_active(make_user, make_match, client_as):
    a = await make_user(name="A"); b = await make_user(name="B"); m = await make_match(a, b)
    s1 = (utc_now() + timedelta(hours=5)).isoformat(); s2 = (utc_now() + timedelta(hours=6)).isoformat()
    async with client_as(a) as c:
        await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": s1})
    async with client_as(b) as c:
        r = await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": s2})
    assert r.status_code == 409
    # active proposal returned in body for the client to flip to review (Flow 6)
    assert r.json()["detail"].get("active_proposal") is not None


# ---------------------------------------------------------------------------
# Task 4.2 — POST /scheduling/calls/{proposal_id}/accept
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_accept_creates_scheduled_call(make_user, make_match, client_as, db):
    a = await make_user(name="A"); b = await make_user(name="B"); m = await make_match(a, b)
    start = (utc_now() + timedelta(hours=5)).isoformat()
    async with client_as(a) as c:
        pid = (await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": start})).json()["id"]
    async with client_as(b) as c:
        r = await c.post(f"/scheduling/calls/{pid}/accept")
    assert r.status_code == 200, r.text
    await db.refresh(m); assert m.call_status == "scheduled"
    assert r.json()["duration_minutes"] == 30
    await db.refresh(a); await db.refresh(b)
    assert a.total_calls_scheduled == 1 and b.total_calls_scheduled == 1


@pytest.mark.asyncio
async def test_proposer_cannot_accept_own_403(make_user, make_match, client_as):
    a = await make_user(name="A"); b = await make_user(name="B"); m = await make_match(a, b)
    start = (utc_now() + timedelta(hours=5)).isoformat()
    async with client_as(a) as c:
        pid = (await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": start})).json()["id"]
        r = await c.post(f"/scheduling/calls/{pid}/accept")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_accept_non_pending_409(make_user, make_match, client_as, db):
    a = await make_user(name="A"); b = await make_user(name="B"); m = await make_match(a, b)
    start = (utc_now() + timedelta(hours=5)).isoformat()
    async with client_as(a) as c:
        pid = (await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": start})).json()["id"]
    async with client_as(b) as c:
        await c.post(f"/scheduling/calls/{pid}/accept")
        r = await c.post(f"/scheduling/calls/{pid}/accept")  # already accepted
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Task 4.3 — POST /scheduling/calls/{proposal_id}/counter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_counter_supersedes(make_user, make_match, client_as, db):
    from sqlalchemy import select
    from app import models
    a = await make_user(name="A"); b = await make_user(name="B"); m = await make_match(a, b)
    s1 = (utc_now() + timedelta(hours=5)).isoformat(); s2 = (utc_now() + timedelta(hours=6)).isoformat()
    async with client_as(a) as c:
        pid = (await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": s1})).json()["id"]
    async with client_as(b) as c:
        r = await c.post(f"/scheduling/calls/{pid}/counter", json={"proposed_start_utc": s2})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending" and r.json()["proposer_user_id"] == b.id
    rows = (await db.execute(select(models.VideoCallProposal).where(models.VideoCallProposal.match_id == m.id))).scalars().all()
    statuses = sorted(p.status for p in rows)
    assert statuses == ["pending", "superseded"]
    await db.refresh(m); assert m.call_status == "proposal_pending"


@pytest.mark.asyncio
async def test_proposer_cannot_counter_own_403(make_user, make_match, client_as):
    a = await make_user(name="A"); b = await make_user(name="B"); m = await make_match(a, b)
    s1 = (utc_now() + timedelta(hours=5)).isoformat(); s2 = (utc_now() + timedelta(hours=6)).isoformat()
    async with client_as(a) as c:
        pid = (await c.post("/scheduling/calls/propose", json={"match_id": m.id, "proposed_start_utc": s1})).json()["id"]
        r = await c.post(f"/scheduling/calls/{pid}/counter", json={"proposed_start_utc": s2})
    assert r.status_code == 403
