"""Tasks 4.6 + 4.7 — no-show detection core + endpoint, and exit-survey /
contact / reveal-contact endpoints.

Runs against the Postgres test harness (tests/conftest_pg.py).
"""
import pytest
from datetime import timedelta

from sqlalchemy import func, select

from app import models
from app.services import match_state_service as mss
from app.services.match_state_service import utc_now


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_past_call(db, match, user1, user2, **overrides):
    """Create a scheduled call whose start is well beyond the 10-min grace."""
    start = utc_now() - timedelta(minutes=30)
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


async def _no_show_event_count(db, match_id, user_id=None):
    q = select(func.count(models.NoShowEvent.id)).where(
        models.NoShowEvent.match_id == match_id
    )
    if user_id is not None:
        q = q.where(models.NoShowEvent.user_id == user_id)
    return (await db.execute(q)).scalar()


# ---------------------------------------------------------------------------
# Task 4.6 — no-show endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_no_show(make_user, make_match, client_as, db):
    a = await make_user(name="Alex"); b = await make_user(name="Mia")
    m = await make_match(a, b)
    # user1=a joined, user2=b did not.
    call = await _make_past_call(db, m, a, b, user1_joined=True, user2_joined=False)

    async with client_as(a) as c:
        r = await c.post(f"/scheduling/calls/{call.id}/no-show")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["no_show_count"] == 1
    assert body["match_terminated"] is False

    await db.refresh(call); await db.refresh(m); await db.refresh(b)
    assert call.status == "no_show"
    assert m.call_status == "no_show"
    assert m.lifecycle == "active"
    assert await _no_show_event_count(db, m.id) == 1
    assert await _no_show_event_count(db, m.id, b.id) == 1
    assert b.no_show_count == 1
    assert b.last_no_show_at is not None


@pytest.mark.asyncio
async def test_both_no_show(make_user, make_match, client_as, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b)
    call = await _make_past_call(db, m, a, b, user1_joined=False, user2_joined=False)

    async with client_as(a) as c:
        r = await c.post(f"/scheduling/calls/{call.id}/no-show")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["no_show_count"] == 2
    assert body["match_terminated"] is False

    await db.refresh(m); await db.refresh(a); await db.refresh(b)
    assert await _no_show_event_count(db, m.id) == 2
    assert a.no_show_count == 1
    assert b.no_show_count == 1
    assert m.lifecycle == "active"


@pytest.mark.asyncio
async def test_second_no_show_same_user_terminates(make_user, make_match, client_as, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b)

    # First call — b never joins. Not terminated.
    call1 = await _make_past_call(db, m, a, b, user1_joined=True, user2_joined=False)
    async with client_as(a) as c:
        r1 = await c.post(f"/scheduling/calls/{call1.id}/no-show")
    assert r1.status_code == 200, r1.text
    assert r1.json()["match_terminated"] is False

    # Match rescheduled — second call, b again never joins. 2nd strike -> terminate.
    call2 = await _make_past_call(db, m, a, b, user1_joined=True, user2_joined=False)
    async with client_as(a) as c:
        r2 = await c.post(f"/scheduling/calls/{call2.id}/no-show")
    assert r2.status_code == 200, r2.text
    assert r2.json()["match_terminated"] is True

    await db.refresh(m); await db.refresh(b)
    assert m.lifecycle == "terminated"
    assert m.text_state == "archived"
    assert await _no_show_event_count(db, m.id, b.id) == 2
    assert b.no_show_count == 2


@pytest.mark.asyncio
async def test_grace_not_elapsed_409(make_user, make_match, client_as, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b)
    start = utc_now() + timedelta(minutes=20)  # in the future
    call = models.ScheduledCall(
        match_id=m.id, user1_id=a.id, user2_id=b.id,
        scheduled_start_utc=start, scheduled_end_utc=start + timedelta(minutes=30),
        duration_minutes=30, status="scheduled",
    )
    db.add(call); await db.commit(); await db.refresh(call)

    async with client_as(a) as c:
        r = await c.post(f"/scheduling/calls/{call.id}/no-show")
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_no_show_already_processed_409(make_user, make_match, client_as, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b)
    call = await _make_past_call(db, m, a, b, user1_joined=True, user2_joined=False, status="completed")
    async with client_as(a) as c:
        r = await c.post(f"/scheduling/calls/{call.id}/no-show")
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_no_show_call_not_found_404(make_user, client_as):
    a = await make_user(name="Al")
    async with client_as(a) as c:
        r = await c.post("/scheduling/calls/999999/no-show")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_no_show_non_participant_403(make_user, make_match, client_as, db):
    """A user who is not on the call's match cannot trigger a no-show, and no
    state is mutated for the would-be victim."""
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    stranger = await make_user(name="Eve")
    m = await make_match(a, b)
    call = await _make_past_call(db, m, a, b, user1_joined=False, user2_joined=False)
    async with client_as(stranger) as c:
        r = await c.post(f"/scheduling/calls/{call.id}/no-show")
    assert r.status_code == 403, r.text
    await db.refresh(call); await db.refresh(a); await db.refresh(b)
    assert call.status == "scheduled"
    assert await _no_show_event_count(db, m.id) == 0
    assert a.no_show_count == 0 and b.no_show_count == 0


@pytest.mark.asyncio
async def test_no_show_ignores_joined_user(make_user, make_match, client_as, db):
    """Non-joiners are derived only from the authoritative join flags — a user
    who actually joined never gets a no-show, even if the caller tries to force
    it via a (now-ignored) body override."""
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b)
    # a (user1) joined; b (user2) did not.
    call = await _make_past_call(db, m, a, b, user1_joined=True, user2_joined=False)
    async with client_as(a) as c:
        # attempt to frame the joined user (a) via the legacy override — must be ignored
        r = await c.post(f"/scheduling/calls/{call.id}/no-show", json={"no_show_user_id": a.id})
    assert r.status_code == 200, r.text
    assert r.json()["no_show_count"] == 1
    await db.refresh(a); await db.refresh(b)
    # only the actually-non-joined user (b) is penalized; the joined user (a) is untouched
    assert await _no_show_event_count(db, m.id, a.id) == 0
    assert a.no_show_count == 0
    assert await _no_show_event_count(db, m.id, b.id) == 1
    assert b.no_show_count == 1


@pytest.mark.asyncio
async def test_no_show_both_joined_no_event(make_user, make_match, client_as, db):
    """If both participants joined, no no-show is fabricated."""
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b)
    call = await _make_past_call(db, m, a, b, user1_joined=True, user2_joined=True)
    async with client_as(a) as c:
        r = await c.post(f"/scheduling/calls/{call.id}/no-show")
    assert r.status_code == 200, r.text
    assert r.json() == {"no_show_count": 0, "match_terminated": False}
    await db.refresh(call); await db.refresh(m)
    assert call.status == "scheduled"          # unchanged
    assert m.call_status != "no_show"
    assert await _no_show_event_count(db, m.id) == 0


# ---------------------------------------------------------------------------
# Task 4.7 — exit-survey
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exit_survey_mutual_yes_unlocks_contact(make_user, make_match, client_as, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    b.phone_number = "5551234567"; b.phone_country_code = "+1"
    m = await make_match(a, b, call_status="pending_survey", text_state="locked")
    await db.commit()

    # A says yes -> still pending (peer hasn't responded).
    async with client_as(a) as c:
        r1 = await c.post(f"/matches/{m.id}/exit-survey", json={"response": True})
    assert r1.status_code == 200, r1.text
    assert r1.json()["call_status"] == "pending_survey"
    assert r1.json()["contact_reveal_unlocked"] is False

    # B says yes -> completed, text open, contact unlocked.
    async with client_as(b) as c:
        r2 = await c.post(f"/matches/{m.id}/exit-survey", json={"response": True})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["call_status"] == "completed"
    assert body["text_state"] == "open"
    assert body["contact_reveal_unlocked"] is True

    # A can now read B's contact.
    async with client_as(a) as c:
        rc = await c.get(f"/matches/{m.id}/contact")
    assert rc.status_code == 200, rc.text
    assert rc.json()["peer_phone_number"] == "5551234567"
    assert rc.json()["peer_phone_country_code"] == "+1"

    # A re-submitting after both responded: mutual-yes already moved the match to
    # call_status='completed', so the survey is no longer pending -> 400.
    # (The 409 'already_responded' guard in the service is only reachable while the
    # match is still 'pending_survey', which the both-responded outcomes never are.)
    async with client_as(a) as c:
        r3 = await c.post(f"/matches/{m.id}/exit-survey", json={"response": True})
    assert r3.status_code == 400, r3.text


@pytest.mark.asyncio
async def test_exit_survey_not_pending_400(make_user, make_match, client_as, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b)  # call_status defaults to 'none'
    async with client_as(a) as c:
        r = await c.post(f"/matches/{m.id}/exit-survey", json={"response": True})
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_exit_survey_no_terminates(make_user, make_match, client_as, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b, call_status="pending_survey", text_state="locked")
    await db.commit()
    async with client_as(a) as c:
        r = await c.post(f"/matches/{m.id}/exit-survey", json={"response": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["match_lifecycle"] == "terminated"
    assert body["text_state"] == "archived"


@pytest.mark.asyncio
async def test_exit_survey_non_participant_403(make_user, make_match, client_as, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo"); c2 = await make_user(name="C")
    m = await make_match(a, b, call_status="pending_survey")
    await db.commit()
    async with client_as(c2) as c:
        r = await c.post(f"/matches/{m.id}/exit-survey", json={"response": True})
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Task 4.7 — contact / reveal-contact
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contact_locked_403(make_user, make_match, client_as, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b)  # contact_reveal_unlocked defaults False
    async with client_as(a) as c:
        r = await c.get(f"/matches/{m.id}/contact")
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_reveal_contact_stamps_timestamp(make_user, make_match, client_as, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b, contact_reveal_unlocked=True)
    await db.commit()

    # A is user_a -> stamps contact_revealed_to_user_a_at.
    async with client_as(a) as c:
        r = await c.post(f"/matches/{m.id}/reveal-contact")
    assert r.status_code == 200, r.text
    assert "revealed_at" in r.json()
    await db.refresh(m)
    assert m.contact_revealed_to_user_a_at is not None
    assert m.contact_revealed_to_user_b_at is None

    # B is user_b -> stamps contact_revealed_to_user_b_at.
    async with client_as(b) as c:
        r2 = await c.post(f"/matches/{m.id}/reveal-contact")
    assert r2.status_code == 200, r2.text
    await db.refresh(m)
    assert m.contact_revealed_to_user_b_at is not None


@pytest.mark.asyncio
async def test_reveal_contact_locked_403(make_user, make_match, client_as, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b)  # locked
    async with client_as(a) as c:
        r = await c.post(f"/matches/{m.id}/reveal-contact")
    assert r.status_code == 403, r.text
