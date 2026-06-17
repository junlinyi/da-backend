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
# Regression — send_message request body schema (Scheduling V2 phone-mask
# regression). `app.schemas` had defined `MessageCreate` TWICE; the second
# (legacy, MessageBase-derived) definition shadowed the intended lightweight one
# and required conversation_id/sender_id, so the iOS client's body
# ({content, message_type}) was rejected with HTTP 422 BEFORE send_message ran —
# meaning masking never happened. This guards the contract the iOS client uses:
# the endpoint's MessageCreate must accept content (+ optional message_type)
# alone, with NO conversation_id / sender_id required.
# ---------------------------------------------------------------------------

@pytest.mark.nodb
def test_message_create_accepts_ios_body_shape():
    # Exactly what ChatViewModel.MessageCreateData encodes.
    from app.routers.messaging import MessageCreate as RouterMessageCreate

    m = RouterMessageCreate(content="hello", message_type="text")
    assert m.content == "hello"
    assert m.message_type == "text"

    # message_type is optional (defaults to text).
    m2 = RouterMessageCreate(content="hi")
    assert m2.content == "hi"

    # And it must NOT require conversation_id / sender_id.
    fields = set(RouterMessageCreate.model_fields.keys())
    assert "conversation_id" not in fields
    assert "sender_id" not in fields


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
        sender_id=a.id, recipient_id=b.id, content=masked_content,
        message_type="text", db=db, has_masked_content=masked,
    )

    row = (await db.execute(
        select(models.Message).where(models.Message.conversation_id == conv.id)
    )).scalar_one()
    assert "[phone hidden]" in row.content
    assert "555-123-4567" not in row.content
    assert row.has_masked_content is True


# ---------------------------------------------------------------------------
# Task 9A-3 — message mirror resolves the PG Conversation by participant PAIR
# (previously a silent no-op because it matched Conversation.id against the
# Firestore string doc id). Proves a mirror row is written with correct fields.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mirror_resolves_conversation_by_pair(db, make_user):
    a = await make_user(name="A")
    b = await make_user(name="B")
    conv = models.Conversation(user1_id=a.id, user2_id=b.id)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    await create_message_in_postgresql(
        sender_id=a.id, recipient_id=b.id, content="hi there",
        message_type="text", db=db, has_masked_content=False,
    )

    row = (await db.execute(
        select(models.Message).where(models.Message.conversation_id == conv.id)
    )).scalar_one()
    assert row.conversation_id == conv.id  # resolved the EXISTING pair conversation
    assert row.sender_id == a.id
    assert row.content == "hi there"
    assert row.message_type == "text"
    assert row.has_masked_content is False


@pytest.mark.asyncio
async def test_mirror_creates_conversation_when_missing(db, make_user):
    """If no PG Conversation exists for the pair yet, the mirror creates one
    rather than silently dropping the row."""
    a = await make_user(name="A")
    b = await make_user(name="B")
    # No Conversation row created up front.

    await create_message_in_postgresql(
        sender_id=a.id, recipient_id=b.id, content="first message",
        message_type="text", db=db, has_masked_content=False,
    )

    conv = (await db.execute(
        select(models.Conversation).where(
            ((models.Conversation.user1_id == a.id) & (models.Conversation.user2_id == b.id))
            | ((models.Conversation.user1_id == b.id) & (models.Conversation.user2_id == a.id))
        )
    )).scalar_one()
    row = (await db.execute(
        select(models.Message).where(models.Message.conversation_id == conv.id)
    )).scalar_one()
    assert row.sender_id == a.id
    assert row.content == "first message"


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
