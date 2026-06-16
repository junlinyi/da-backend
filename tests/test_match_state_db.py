"""DB-bound tests for the Scheduling V2 match-state machine.

Uses the Postgres harness fixtures (db, make_user, make_match). The service
functions use db.flush() (not commit); tests refresh/commit and assert.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import match_state_service as mss


def _aware(dt):
    """Normalize to tz-aware UTC for comparison (asyncpg returns tz-aware)."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# transition_call_status
# ---------------------------------------------------------------------------

async def test_transition_call_status_legal(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b)  # call_status defaults to "none"

    res = await mss.transition_call_status(db, m.id, "proposal_pending")
    await db.commit()
    await db.refresh(res)
    assert res.call_status == "proposal_pending"


async def test_transition_call_status_illegal(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b)  # "none" -> "scheduled" is illegal

    with pytest.raises(ValueError, match="illegal_call_status"):
        await mss.transition_call_status(db, m.id, "scheduled")


# ---------------------------------------------------------------------------
# transition_text_state
# ---------------------------------------------------------------------------

async def test_transition_text_state_lock_sets_timestamps(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b)  # text_state defaults to "open"

    before = mss.utc_now()
    res = await mss.transition_text_state(db, m.id, "locked")
    after = mss.utc_now()
    await db.commit()
    await db.refresh(res)

    assert res.text_state == "locked"
    locked_at = _aware(res.text_locked_at)
    expires_at = _aware(res.expires_at)
    assert locked_at is not None
    assert before <= locked_at <= after
    # expires_at = text_locked_at + 72h
    assert expires_at == locked_at + timedelta(hours=mss.PROPOSAL_WINDOW_HOURS)


async def test_transition_text_state_unlock_sets_unlocked_at(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b, text_state="locked")

    res = await mss.transition_text_state(db, m.id, "open")
    await db.commit()
    await db.refresh(res)

    assert res.text_state == "open"
    assert _aware(res.text_unlocked_at) is not None


async def test_transition_text_state_illegal(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b, text_state="archived")

    with pytest.raises(ValueError, match="illegal_text_state"):
        await mss.transition_text_state(db, m.id, "open")


# ---------------------------------------------------------------------------
# process_exit_survey
# ---------------------------------------------------------------------------

async def test_exit_survey_first_yes_stays_pending(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b, call_status="pending_survey", text_state="locked")

    res = await mss.process_exit_survey(db, m.id, a.id, True)
    await db.commit()
    await db.refresh(res)

    assert res.call_status == "pending_survey"  # unchanged, partner not yet in
    assert res.exit_survey_user_a_response is True
    assert res.exit_survey_user_b_response is None
    assert _aware(res.exit_survey_user_a_responded_at) is not None
    assert res.lifecycle == "active"
    assert res.contact_reveal_unlocked is False


async def test_exit_survey_both_yes_completes_and_unlocks(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b, call_status="pending_survey", text_state="locked")

    await mss.process_exit_survey(db, m.id, a.id, True)
    res = await mss.process_exit_survey(db, m.id, b.id, True)
    await db.commit()
    await db.refresh(res)

    assert res.call_status == "completed"
    assert res.text_state == "open"
    assert res.contact_reveal_unlocked is True
    assert _aware(res.text_unlocked_at) is not None
    assert res.lifecycle == "active"


async def test_exit_survey_one_no_terminates(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b, call_status="pending_survey", text_state="locked")

    await mss.process_exit_survey(db, m.id, a.id, True)
    res = await mss.process_exit_survey(db, m.id, b.id, False)
    await db.commit()
    await db.refresh(res)

    assert res.lifecycle == "terminated"
    assert res.text_state == "archived"
    assert res.contact_reveal_unlocked is False


async def test_exit_survey_first_no_terminates_immediately(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b, call_status="pending_survey", text_state="locked")

    res = await mss.process_exit_survey(db, m.id, a.id, False)
    await db.commit()
    await db.refresh(res)

    assert res.lifecycle == "terminated"
    assert res.text_state == "archived"


async def test_exit_survey_mutable_by_self_before_partner(db, make_user, make_match):
    """User may change their own response while partner has not responded."""
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b, call_status="pending_survey", text_state="locked")

    await mss.process_exit_survey(db, m.id, a.id, True)
    # Same user changes mind to no (allowed: partner response still None).
    res = await mss.process_exit_survey(db, m.id, a.id, False)
    await db.commit()
    await db.refresh(res)

    # Self changed to no -> termination triggers on the joint evaluation.
    assert res.exit_survey_user_a_response is False
    assert res.lifecycle == "terminated"
    assert res.text_state == "archived"


async def test_exit_survey_mutable_by_self_yes_to_yes_stays_pending(db, make_user, make_match):
    """Self can resubmit (e.g. yes->yes) while partner unresponded; stays pending."""
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b, call_status="pending_survey", text_state="locked")

    await mss.process_exit_survey(db, m.id, a.id, True)
    res = await mss.process_exit_survey(db, m.id, a.id, True)
    await db.commit()
    await db.refresh(res)

    assert res.exit_survey_user_a_response is True
    assert res.exit_survey_user_b_response is None
    assert res.call_status == "pending_survey"


async def test_exit_survey_immutable_after_both_responded(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b, call_status="pending_survey", text_state="locked")

    await mss.process_exit_survey(db, m.id, a.id, True)
    await mss.process_exit_survey(db, m.id, b.id, True)
    await db.commit()

    # call_status is now "completed", so this raises not_pending_survey first;
    # but to specifically exercise "already_responded" we need a state where
    # both responded yet status stayed pending_survey — impossible via yes/yes.
    # So assert the realistic guard: further submits are rejected.
    with pytest.raises(ValueError):
        await mss.process_exit_survey(db, m.id, a.id, False)


async def test_exit_survey_already_responded_guard(db, make_user, make_match):
    """Directly exercise 'already_responded': both responses present while
    call_status is still pending_survey (e.g. one yes + one no leaves status
    pending but terminated). Construct the both-recorded case with status forced
    to pending_survey to hit the immutability guard."""
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(
        a, b,
        call_status="pending_survey",
        text_state="locked",
        exit_survey_user_a_response=True,
        exit_survey_user_a_responded_at=datetime.now(timezone.utc),
        exit_survey_user_b_response=True,
        exit_survey_user_b_responded_at=datetime.now(timezone.utc),
    )

    with pytest.raises(ValueError, match="already_responded"):
        await mss.process_exit_survey(db, m.id, a.id, False)


async def test_exit_survey_not_pending_raises(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b, call_status="scheduled", text_state="locked")

    with pytest.raises(ValueError, match="not_pending_survey"):
        await mss.process_exit_survey(db, m.id, a.id, True)
