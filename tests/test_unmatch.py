"""DB-bound tests for user-initiated unmatch (Pass-4 backend gap #1).

Exercises the match-state service: unmatch() terminates the match + closes the
conversation, is idempotent, and get_terminated_match_user_ids() surfaces the
peer for both participants so Discover can exclude them.
"""
import pytest

from app import models
from app.services import match_state_service as mss


async def _make_conversation(db, user_a, user_b, is_active=True):
    conv = models.Conversation(user1_id=user_a.id, user2_id=user_b.id, is_active=is_active)
    db.add(conv); await db.commit(); await db.refresh(conv)
    return conv


async def test_unmatch_terminates_and_closes_conversation(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b)  # lifecycle defaults to "active", text_state "open"
    conv = await _make_conversation(db, a, b, is_active=True)

    res = await mss.unmatch(db, m.id)
    await db.commit()
    await db.refresh(res)
    await db.refresh(conv)

    assert res.lifecycle == "terminated"
    assert res.text_state == "archived"
    assert conv.is_active is False


async def test_unmatch_idempotent_when_already_terminated(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b, lifecycle="terminated", text_state="archived")

    res = await mss.unmatch(db, m.id)  # must not raise
    await db.commit()
    await db.refresh(res)

    assert res.lifecycle == "terminated"
    assert res.text_state == "archived"


async def test_unmatch_unknown_match_raises(db):
    with pytest.raises(ValueError, match="match_not_found"):
        await mss.unmatch(db, 999999)


async def test_terminated_match_excluded_for_both_users(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b)
    await mss.unmatch(db, m.id)
    await db.commit()

    a_excludes = await mss.get_terminated_match_user_ids(db, a.id)
    b_excludes = await mss.get_terminated_match_user_ids(db, b.id)

    assert b.id in a_excludes  # A no longer sees B
    assert a.id in b_excludes  # B no longer sees A


async def test_active_match_not_excluded(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    await make_match(a, b)  # still active

    assert await mss.get_terminated_match_user_ids(db, a.id) == set()
