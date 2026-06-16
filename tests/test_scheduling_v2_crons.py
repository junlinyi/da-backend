"""Phase 6 (Tasks 6.1–6.3) — Scheduling V2 cron BODIES.

Tests the cron functions directly against the Postgres harness (conftest_pg.py).
The asyncio loop timing is NOT tested here — only the per-tick body semantics.
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

async def _make_conversation(db, a, b):
    conv = models.Conversation(user1_id=a.id, user2_id=b.id)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def _system_message_count(db, conversation_id, system_message_type=None):
    q = select(func.count(models.Message.id)).where(
        models.Message.conversation_id == conversation_id,
        models.Message.message_type == "system",
    )
    if system_message_type is not None:
        q = q.where(models.Message.system_message_type == system_message_type)
    return (await db.execute(q)).scalar()


# ---------------------------------------------------------------------------
# Task 6.1 — lock_text_for_eligible_matches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lock_text_after_24h(make_user, make_match, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    c = await make_user(name="Cy"); d = await make_user(name="De")
    # Eligible: created 25h ago, open/active.
    old = await make_match(a, b, created_at=utc_now() - timedelta(hours=25))
    # Not eligible: created 1h ago (distinct pair to avoid unique constraint).
    young = await make_match(c, d, created_at=utc_now() - timedelta(hours=1))
    await db.commit()

    locked = await mss.lock_text_for_eligible_matches(db)
    assert locked == 1

    await db.refresh(old); await db.refresh(young)
    assert old.text_state == "locked"
    assert old.text_locked_at is not None
    # expires_at == locked + 72h (±5s)
    delta = abs((old.expires_at - (old.text_locked_at + timedelta(hours=72))).total_seconds())
    assert delta < 5
    assert young.text_state == "open"


@pytest.mark.asyncio
async def test_lock_text_writes_system_message_when_none(make_user, make_match, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    await _make_conversation(db, a, b)
    m = await make_match(a, b, created_at=utc_now() - timedelta(hours=25), call_status="none")
    await db.commit()

    await mss.lock_text_for_eligible_matches(db)

    conv = await mss._resolve_conversation_for_match(db, m)
    assert await _system_message_count(db, conv.id, "text_locked") == 1


@pytest.mark.asyncio
async def test_lock_text_skips_message_when_scheduled(make_user, make_match, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    await _make_conversation(db, a, b)
    m = await make_match(
        a, b, created_at=utc_now() - timedelta(hours=25), call_status="scheduled"
    )
    await db.commit()

    locked = await mss.lock_text_for_eligible_matches(db)
    assert locked == 1  # still locks the text

    await db.refresh(m)
    assert m.text_state == "locked"
    conv = await mss._resolve_conversation_for_match(db, m)
    assert await _system_message_count(db, conv.id, "text_locked") == 0


@pytest.mark.asyncio
async def test_notify_text_window_nudges_runs(make_user, make_match, db):
    """Nudge cron is best-effort; verify it runs and returns a count without error."""
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    # ~19h elapsed -> 5h remaining nudge candidate.
    await make_match(a, b, created_at=utc_now() - timedelta(hours=19, minutes=1),
                     call_status="none")
    await db.commit()
    n = await mss.notify_text_window_nudges(db)
    assert isinstance(n, int)


# ---------------------------------------------------------------------------
# Task 6.2 — expire_unscheduled_matches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expire_after_72h(make_user, make_match, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(
        a, b, text_state="locked", call_status="none", lifecycle="active",
        text_locked_at=utc_now() - timedelta(hours=73),
    )
    await db.commit()

    expired = await mss.expire_unscheduled_matches(db)
    assert expired == 1

    await db.refresh(m)
    assert m.lifecycle == "expired"
    assert m.text_state == "archived"


@pytest.mark.asyncio
async def test_expire_protects_scheduled(make_user, make_match, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(
        a, b, text_state="locked", call_status="scheduled", lifecycle="active",
        text_locked_at=utc_now() - timedelta(hours=73),
    )
    await db.commit()

    expired = await mss.expire_unscheduled_matches(db)
    assert expired == 0

    await db.refresh(m)
    assert m.lifecycle == "active"
    assert m.text_state == "locked"


@pytest.mark.asyncio
async def test_expire_includes_no_show(make_user, make_match, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(
        a, b, text_state="locked", call_status="no_show", lifecycle="active",
        text_locked_at=utc_now() - timedelta(hours=73),
    )
    await db.commit()

    expired = await mss.expire_unscheduled_matches(db)
    assert expired == 1

    await db.refresh(m)
    assert m.lifecycle == "expired"
    assert m.text_state == "archived"


@pytest.mark.asyncio
async def test_expire_skips_young_locked(make_user, make_match, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(
        a, b, text_state="locked", call_status="none", lifecycle="active",
        text_locked_at=utc_now() - timedelta(hours=1),
    )
    await db.commit()

    assert await mss.expire_unscheduled_matches(db) == 0
    await db.refresh(m)
    assert m.lifecycle == "active"


# ---------------------------------------------------------------------------
# Task 9A-2 — notify_expiring_soon_matches (24h-before-expiry push)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_match_expiring_soon_fires_once_at_48h(make_user, make_match, db, monkeypatch):
    """A locked/active/none match whose text_locked_at crossed 48h-elapsed within
    the last tick fires match_expiring_soon once (to both participants)."""
    import app.services.push_notification_service as push

    calls = []

    async def _counter(recipient, peer_name, match_id, **kw):
        calls.append((recipient.id if recipient else None, match_id))

    monkeypatch.setattr(push, "notify_match_expiring_soon", _counter)

    a = await make_user(name="Al"); b = await make_user(name="Bo")
    # 49h since lock -> crossed the 48h threshold ~1h ago. Within a 300s tick edge?
    # The cron edge window is (now-48h-300s, now-48h]; 49h-ago is INSIDE neither —
    # use a value that lands in the tick window: now - 48h - 1min.
    m = await make_match(
        a, b, text_state="locked", call_status="none", lifecycle="active",
        text_locked_at=utc_now() - timedelta(hours=48, minutes=1),
    )
    await db.commit()

    attempted = await mss.notify_expiring_soon_matches(db)
    assert attempted == 1
    # Pushed to BOTH participants for the one match.
    assert len(calls) == 2
    assert {c[1] for c in calls} == {m.id}
    assert {c[0] for c in calls} == {a.id, b.id}


@pytest.mark.asyncio
async def test_match_expiring_soon_skips_recently_locked(make_user, make_match, db, monkeypatch):
    """A match only 10h into its window must NOT fire match_expiring_soon."""
    import app.services.push_notification_service as push

    calls = []

    async def _counter(recipient, peer_name, match_id, **kw):
        calls.append(match_id)

    monkeypatch.setattr(push, "notify_match_expiring_soon", _counter)

    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(
        a, b, text_state="locked", call_status="none", lifecycle="active",
        text_locked_at=utc_now() - timedelta(hours=10),
    )
    await db.commit()

    attempted = await mss.notify_expiring_soon_matches(db)
    assert attempted == 0
    assert calls == []


# ---------------------------------------------------------------------------
# Task 6.3 — detect_no_shows
# ---------------------------------------------------------------------------

async def _make_call(db, match, user1, user2, **overrides):
    start = utc_now() - timedelta(minutes=15)
    kwargs = dict(
        match_id=match.id, user1_id=user1.id, user2_id=user2.id,
        scheduled_start_utc=start, scheduled_end_utc=start + timedelta(minutes=30),
        duration_minutes=30, status="scheduled",
    )
    kwargs.update(overrides)
    call = models.ScheduledCall(**kwargs)
    db.add(call); await db.commit(); await db.refresh(call)
    return call


@pytest.mark.asyncio
async def test_detect_no_shows(make_user, make_match, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b, text_state="locked", call_status="scheduled")
    # past start, a joined, b did not -> b no-shows.
    call = await _make_call(db, m, a, b, user1_joined=True, user2_joined=False)

    processed = await mss.detect_no_shows(db)
    assert processed == 1

    await db.refresh(call); await db.refresh(m); await db.refresh(b)
    assert call.status == "no_show"
    assert m.call_status == "no_show"
    # one NoShowEvent for b, none for a.
    cnt_b = (await db.execute(
        select(func.count(models.NoShowEvent.id)).where(
            models.NoShowEvent.match_id == m.id, models.NoShowEvent.user_id == b.id)
    )).scalar()
    cnt_a = (await db.execute(
        select(func.count(models.NoShowEvent.id)).where(
            models.NoShowEvent.match_id == m.id, models.NoShowEvent.user_id == a.id)
    )).scalar()
    assert cnt_b == 1
    assert cnt_a == 0
    assert b.no_show_count == 1


@pytest.mark.asyncio
async def test_detect_no_shows_future_untouched(make_user, make_match, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b, call_status="scheduled")
    start = utc_now() + timedelta(minutes=10)
    call = await _make_call(
        db, m, a, b, scheduled_start_utc=start,
        scheduled_end_utc=start + timedelta(minutes=30),
        user1_joined=False, user2_joined=False,
    )

    assert await mss.detect_no_shows(db) == 0
    await db.refresh(call)
    assert call.status == "scheduled"


@pytest.mark.asyncio
async def test_detect_no_shows_both_joined_untouched(make_user, make_match, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b, call_status="scheduled")
    call = await _make_call(db, m, a, b, user1_joined=True, user2_joined=True)

    assert await mss.detect_no_shows(db) == 0
    await db.refresh(call); await db.refresh(m)
    assert call.status == "scheduled"
    assert m.call_status == "scheduled"


# ---------------------------------------------------------------------------
# Task 7.2 — send_date_reminders
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_date_reminder_15min_sets_reminder_sent(make_user, make_match, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b, call_status="scheduled")
    start = utc_now() + timedelta(minutes=10)  # within 15-min window
    call = await _make_call(
        db, m, a, b, scheduled_start_utc=start,
        scheduled_end_utc=start + timedelta(minutes=30),
    )
    assert call.reminder_sent is False

    attempted = await mss.send_date_reminders(db)
    await db.commit()
    await db.refresh(call)
    assert attempted >= 1
    assert call.reminder_sent is True

    # Second tick must NOT re-send the 15-min reminder (deduped).
    assert await mss.send_date_reminders(db) == 0


@pytest.mark.asyncio
async def test_date_reminder_future_untouched(make_user, make_match, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b, call_status="scheduled")
    start = utc_now() + timedelta(hours=3)  # too far out
    call = await _make_call(
        db, m, a, b, scheduled_start_utc=start,
        scheduled_end_utc=start + timedelta(minutes=30),
    )

    assert await mss.send_date_reminders(db) == 0
    await db.refresh(call)
    assert call.reminder_sent is False


@pytest.mark.asyncio
async def test_date_reminder_starting_now(make_user, make_match, db):
    a = await make_user(name="Al"); b = await make_user(name="Bo")
    m = await make_match(a, b, call_status="scheduled")
    start = utc_now() - timedelta(seconds=30)  # just started, within tick window
    call = await _make_call(
        db, m, a, b, scheduled_start_utc=start,
        scheduled_end_utc=start + timedelta(minutes=30),
        reminder_sent=True,  # 15-min already sent earlier
    )

    # Should fire the "starting now" reminder (does not depend on reminder_sent).
    attempted = await mss.send_date_reminders(db)
    assert attempted >= 1
