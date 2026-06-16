"""Scheduling V2 match-state machine. Owns transitions of the three orthogonal
dimensions (text_state, call_status, lifecycle) and the card-display helper."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models


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
