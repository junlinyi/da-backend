"""Tests for Scheduling V2 Phase 5: chat text-lock gate, phone-mask mirror, and
the system-message writer (Firestore + Postgres mirror).

Firestore coverage caveat
-------------------------
The chat send path (`messaging.send_message`) is FIRESTORE-authoritative: it
verifies the conversation doc, writes the message + lastMessage to Firestore, and
ONLY mirrors to Postgres for analytics. There is no Firestore emulator in this
harness, so the full `send_message` request cannot be exercised end-to-end here.

Instead we cover the pure, server-side V2 logic that the request path delegates
to, which is where all the gating/masking decisions live:
  * `assert_text_open(match)` — the 403 gate (unit).
  * `create_message_in_postgresql(..., has_masked_content=...)` — the mirror-row
    fields including the masked content + flag (DB).
  * `filter_message_content` is unit-tested in test_chat_filter_unit.py.
The system-message writer's Postgres mirror is tested directly + via the
propose/accept endpoints (which run fully server-side, no Firestore needed —
their Firestore writes are best-effort/guarded and no-op in tests).
"""
import pytest
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app import models
from app.routers.messaging import assert_text_open, create_message_in_postgresql
from app.services import match_state_service as mss
from app.services.match_state_service import utc_now


# ---------------------------------------------------------------------------
# Task 5.2 — assert_text_open gate (pure unit, no DB)
# ---------------------------------------------------------------------------

@pytest.mark.nodb
def test_assert_text_open_locked_raises_403():
    with pytest.raises(HTTPException) as ei:
        assert_text_open(models.Match(text_state="locked"))
    assert ei.value.status_code == 403


@pytest.mark.nodb
def test_assert_text_open_archived_raises_403():
    with pytest.raises(HTTPException) as ei:
        assert_text_open(models.Match(text_state="archived"))
    assert ei.value.status_code == 403


@pytest.mark.nodb
def test_assert_text_open_open_returns_none():
    assert assert_text_open(models.Match(text_state="open")) is None


@pytest.mark.nodb
def test_assert_text_open_none_match_does_not_block():
    # None policy: no resolvable V2 Match -> don't block (legacy/edge chats).
    assert assert_text_open(None) is None


# ---------------------------------------------------------------------------
# Task 5.2 — mask is mirrored to the Postgres Message row
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mask_mirrored_to_postgres(db, make_user):
    a = await make_user(name="A")
    b = await make_user(name="B")
    conv = models.Conversation(user1_id=a.id, user2_id=b.id)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    # The send path applies filter_message_content, then mirrors the (masked)
    # content + flag through create_message_in_postgresql. Drive that directly.
    from app.services.chat_message_filter import filter_message_content
    masked_content, masked = filter_message_content("my number is 555-123-4567")
    assert masked is True

    await create_message_in_postgresql(
        str(conv.id), a.id, masked_content, "text", db, has_masked_content=masked,
    )

    row = (await db.execute(
        select(models.Message).where(models.Message.conversation_id == conv.id)
    )).scalar_one()
    assert "[phone hidden]" in row.content
    assert "555-123-4567" not in row.content
    assert row.has_masked_content is True


# ---------------------------------------------------------------------------
# Task 5.3 — write_system_message Postgres mirror
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_system_message_mirrored(db, make_user, make_match):
    a = await make_user(name="A")
    b = await make_user(name="B")
    m = await make_match(a, b)
    conv = models.Conversation(user1_id=a.id, user2_id=b.id)
    db.add(conv)
    await db.commit()

    await mss.write_system_message(db, m, "call_scheduled", "Video date scheduled")
    await db.commit()

    row = (await db.execute(
        select(models.Message).where(
            models.Message.system_message_type == "call_scheduled"
        )
    )).scalar_one()
    assert row.sender_id is None
    assert row.message_type == "system"
    assert row.content == "Video date scheduled"


@pytest.mark.asyncio
async def test_propose_open_creates_system_message(db, make_user, make_match, client_as):
    a = await make_user(name="Alex")
    b = await make_user(name="Mia")
    m = await make_match(a, b)  # text_state defaults to 'open'
    db.add(models.Conversation(user1_id=a.id, user2_id=b.id))
    await db.commit()

    start = (utc_now() + timedelta(hours=5)).isoformat()
    async with client_as(a) as c:
        r = await c.post("/scheduling/calls/propose",
                         json={"match_id": m.id, "proposed_start_utc": start})
    assert r.status_code == 200, r.text

    rows = (await db.execute(
        select(models.Message).where(
            models.Message.system_message_type == "proposal_created"
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].sender_id is None and rows[0].message_type == "system"


@pytest.mark.asyncio
async def test_propose_locked_no_system_message(db, make_user, make_match, client_as):
    a = await make_user(name="Alex")
    b = await make_user(name="Mia")
    m = await make_match(a, b, text_state="locked")  # locked -> no in-chat system msg
    db.add(models.Conversation(user1_id=a.id, user2_id=b.id))
    await db.commit()

    start = (utc_now() + timedelta(hours=5)).isoformat()
    async with client_as(a) as c:
        r = await c.post("/scheduling/calls/propose",
                         json={"match_id": m.id, "proposed_start_utc": start})
    assert r.status_code == 200, r.text

    rows = (await db.execute(
        select(models.Message).where(
            models.Message.system_message_type == "proposal_created"
        )
    )).scalars().all()
    assert rows == []
