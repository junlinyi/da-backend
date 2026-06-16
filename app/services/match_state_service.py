"""Scheduling V2 match-state machine. Owns transitions of the three orthogonal
dimensions (text_state, call_status, lifecycle) and the card-display helper."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Pure transition tables (no DB)
# ---------------------------------------------------------------------------

_LEGAL_CALL_STATUS = {
    "none": {"proposal_pending"},
    "proposal_pending": {"proposal_pending", "scheduled"},
    "scheduled": {"in_progress", "no_show", "proposal_pending"},
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
    # Lifecycle terminal states take priority (read-only cards). Spec table rows
    # `archived | * | terminated` and `archived | * | expired`.
    if lifecycle == "expired":
        return "Match expired"
    if lifecycle == "terminated":
        return "Match ended"
    # Action-needed / call-driven states.
    if call_status == "pending_survey":
        return "Continue texting? Complete survey"
    if call_status == "no_show":
        return "Missed — reschedule video date" if text_state == "locked" else "Texting · Reschedule video date"
    if call_status == "proposal_pending":
        if is_proposer:
            return "Waiting for response"
        return "Texting · Review proposed time" if text_state == "open" else "Review proposed time"
    if call_status in ("scheduled", "in_progress"):
        if call_status == "in_progress":
            return "Video date in progress"
        when = scheduled_start.strftime("%a %-I %p") if scheduled_start else "soon"
        prefix = "Texting · " if text_state == "open" else ""
        return f"{prefix}Video date {when}"
    if call_status == "completed":
        return "Texting · Last date complete"
    # call_status == "none"
    if text_state == "locked":
        return "Schedule a video date"
    hl = hours_left if hours_left is not None else 24
    return f"Texting · {hl}h left"


# ---------------------------------------------------------------------------
# DB-bound transitions (row-locked)
# ---------------------------------------------------------------------------

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


async def record_no_show(db: AsyncSession, call: "models.ScheduledCall", no_show_user_ids) -> dict:
    """Mark a scheduled call as no_show, log one NoShowEvent per non-joiner, bump
    users.no_show_count, and apply the 2-strikes-same-match termination.

    Returns dict(no_show_count_logged, match_terminated).
    """
    now = utc_now()
    no_show_user_ids = list(no_show_user_ids)
    call.status = "no_show"
    m = await _lock_match(db, call.match_id)
    m.call_status = "no_show"

    for uid in no_show_user_ids:
        db.add(models.NoShowEvent(
            user_id=uid,
            match_id=call.match_id,
            scheduled_call_id=call.id,
            event_type="no_show",
        ))
        u = (await db.execute(
            select(models.User).where(models.User.id == uid)
        )).scalar_one()
        u.no_show_count = (u.no_show_count or 0) + 1
        u.last_no_show_at = now

    # Flush so the freshly-inserted events are visible to the count query below.
    await db.flush()

    # 2-strikes termination: does ANY single user have >= 2 no-show events on
    # THIS match? Count events grouped by user for this match_id.
    max_events = (await db.execute(
        select(func.count(models.NoShowEvent.id))
        .where(models.NoShowEvent.match_id == call.match_id)
        .group_by(models.NoShowEvent.user_id)
        .order_by(func.count(models.NoShowEvent.id).desc())
        .limit(1)
    )).scalar()

    match_terminated = bool(max_events and max_events >= 2)
    if match_terminated:
        m.lifecycle = "terminated"
        m.text_state = "archived"

    await db.flush()
    return {
        "no_show_count_logged": len(no_show_user_ids),
        "match_terminated": match_terminated,
    }


async def _resolve_conversation_for_match(db: AsyncSession, match: "models.Match"):
    """Find the Postgres Conversation between the match's two users (either order)."""
    a, b = match.user_id, match.matched_user_id
    return (await db.execute(
        select(models.Conversation).where(
            or_(
                (models.Conversation.user1_id == a) & (models.Conversation.user2_id == b),
                (models.Conversation.user1_id == b) & (models.Conversation.user2_id == a),
            )
        )
    )).scalar_one_or_none()


async def write_system_message(db: AsyncSession, match: "models.Match",
                               system_message_type: str, text: str) -> None:
    """Write a system message: a Firestore doc (messageType='system') for
    real-time render, plus a Postgres Message mirror row (sender_id=NULL) for
    analytics.

    The Postgres mirror is part of the caller's session (added but not committed
    here — the caller's commit persists it). The Firestore write is best-effort:
    a Firestore failure (or Firestore being unavailable in tests) is swallowed so
    it never breaks the caller's transaction.
    """
    # 1) Postgres mirror row (sender_id=NULL marks a system message).
    conversation = await _resolve_conversation_for_match(db, match)
    if conversation is not None:
        db.add(models.Message(
            conversation_id=conversation.id,
            sender_id=None,
            content=text,
            message_type="system",
            system_message_type=system_message_type,
        ))
    else:
        logger.info(
            "write_system_message: no Conversation for match %s; skipping PG mirror",
            getattr(match, "id", "?"),
        )

    # 2) Firestore doc — best-effort, reusing messaging.py's path/pattern.
    try:
        from firebase_admin import firestore

        a, b = match.user_id, match.matched_user_id
        user_a = (await db.execute(
            select(models.User).where(models.User.id == a)
        )).scalar_one_or_none()
        user_b = (await db.execute(
            select(models.User).where(models.User.id == b)
        )).scalar_one_or_none()
        if not (user_a and user_b and user_a.firebase_uid and user_b.firebase_uid):
            return

        firestore_db = firestore.client()
        conversations_ref = firestore_db.collection("conversations")
        conversation_id = None
        for doc in conversations_ref.where(
            "participants", "array_contains", user_a.firebase_uid
        ).stream():
            data = doc.to_dict()
            if user_b.firebase_uid in data.get("participants", []):
                conversation_id = doc.id
                break
        if conversation_id is None:
            return

        conv_ref = conversations_ref.document(conversation_id)
        conv_ref.collection("messages").add({
            "senderId": None,
            "content": text,
            "messageType": "system",
            "systemMessageType": system_message_type,
            "timestamp": firestore.SERVER_TIMESTAMP,
        })
        conv_ref.update({
            "lastMessage": text,
            "lastMessageTime": firestore.SERVER_TIMESTAMP,
        })
    except Exception as exc:  # noqa: BLE001 — best-effort mirror
        logger.warning("write_system_message: Firestore write failed: %s", exc)


async def process_exit_survey(db: AsyncSession, match_id: int, user_id: int, response: bool) -> models.Match:
    m = await _lock_match(db, match_id)
    if m.call_status != "pending_survey":
        raise ValueError("not_pending_survey")
    is_a = _is_user_a(m, user_id)
    already = m.exit_survey_user_a_response if is_a else m.exit_survey_user_b_response
    other = m.exit_survey_user_b_response if is_a else m.exit_survey_user_a_response
    # Responses are immutable once BOTH users have responded; mutable-by-self
    # while only the self response is recorded (spec §Notable invariants).
    if already is not None and other is not None:
        raise ValueError("already_responded")
    now = utc_now()
    if is_a:
        m.exit_survey_user_a_response, m.exit_survey_user_a_responded_at = response, now
    else:
        m.exit_survey_user_b_response, m.exit_survey_user_b_responded_at = response, now
    a, b = m.exit_survey_user_a_response, m.exit_survey_user_b_response
    if a is False or b is False:
        m.lifecycle = "terminated"
        m.text_state = "archived"
    elif a is True and b is True:
        m.call_status = "completed"
        m.text_state = "open"
        m.text_unlocked_at = now
        m.contact_reveal_unlocked = True
    await db.flush()
    return m
