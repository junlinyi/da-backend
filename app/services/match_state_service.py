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
NO_SHOW_GRACE_MIN = 10


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


# ---------------------------------------------------------------------------
# Phase 6 — time-based cron BODIES
#
# Each body manages its OWN per-iteration error handling so one bad row can't
# abort the whole tick, but leaves the final commit to the caller (the loop in
# scheduling_monitor_service.py calls each with a fresh session and commits
# after). Push sends are best-effort and Phase 7 (Task 7.1) — guarded by
# hasattr + try/except so tests never depend on push being implemented.
# ---------------------------------------------------------------------------


async def _push_both_participants(db: AsyncSession, match: "models.Match",
                                  fn_name: str, **extra) -> None:
    """Best-effort V2 push to BOTH participants of a match (Task 7.1).

    Resolves both Users, then calls push.<fn_name>(recipient=..., peer_name=...,
    match_id=match.id, **extra) once per recipient (peer_name = the OTHER user's
    name). Any failure is swallowed so a cron tick is never broken by push.
    """
    try:
        from app.services import push_notification_service as push
        fn = getattr(push, fn_name, None)
        if fn is None:
            return
        a = (await db.execute(
            select(models.User).where(models.User.id == match.user_id)
        )).scalar_one_or_none()
        b = (await db.execute(
            select(models.User).where(models.User.id == match.matched_user_id)
        )).scalar_one_or_none()
        for recipient, peer in ((a, b), (b, a)):
            if recipient is None:
                continue
            peer_name = (peer.name if peer else None) or "your match"
            await fn(recipient=recipient, peer_name=peer_name, match_id=match.id, **extra)
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("best-effort push %s failed: %s", fn_name, exc)


async def lock_text_for_eligible_matches(db: AsyncSession) -> int:
    """Lock text for matches whose 24h window elapsed. Returns count locked.

    Selects matches where text_state='open' AND lifecycle='active' AND
    created_at < now - 24h. For each: text_state='locked', text_locked_at=now,
    expires_at=now+72h. If call_status='none', writes a 'text_locked' system
    message + best-effort push (skipped when a date is already scheduled).
    """
    now = utc_now()
    cutoff = now - timedelta(hours=TEXT_WINDOW_HOURS)
    rows = (await db.execute(
        select(models.Match).where(
            models.Match.text_state == "open",
            models.Match.lifecycle == "active",
            models.Match.created_at < cutoff,
        )
    )).scalars().all()

    locked = 0
    for m in rows:
        try:
            m.text_state = "locked"
            m.text_locked_at = now
            m.expires_at = now + timedelta(hours=PROPOSAL_WINDOW_HOURS)
            await db.flush()
            # Only nudge if no date is committed yet (spec §Service Logic).
            if m.call_status == "none":
                await write_system_message(
                    db, m, "text_locked",
                    "Text paused. Schedule your video date to take it to the next level.",
                )
                await _push_both_participants(db, m, "notify_text_locked")
            locked += 1
        except Exception as exc:  # noqa: BLE001 — isolate one bad row
            logger.error("lock_text_for_eligible_matches failed for match %s: %s",
                         m.id, exc, exc_info=True)
            continue
    return locked


async def notify_text_window_nudges(db: AsyncSession) -> int:
    """Best-effort pre-lock nudges. Returns number of pushes attempted.

    Fires text_window_5h_remaining at ~19h elapsed (5h remaining) and
    text_window_locking at ~23h elapsed (1h remaining), for open/active matches
    with call_status='none'.

    Dedup: this loop runs every 60s, so each match would otherwise match the
    "19h elapsed" predicate for a full hour (60 ticks). We restrict each nudge
    to a 1-tick-wide window (the slice of `created_at` that crosses the threshold
    within the last 60s) so each match fires at most once per threshold. This is
    a best-effort approximation — if a tick is missed the nudge is simply skipped
    rather than re-sent on the next tick.
    """
    now = utc_now()
    tick = timedelta(seconds=60)
    attempted = 0

    # 5h-remaining: elapsed crossed 19h within the last tick, i.e.
    # created_at fell into (now-19h-60s, now-19h].
    edge_5h_hi = now - timedelta(hours=19)
    edge_5h_lo = edge_5h_hi - tick
    # 1h-remaining: elapsed crossed 23h within the last tick.
    edge_1h_hi = now - timedelta(hours=23)
    edge_1h_lo = edge_1h_hi - tick

    for push_name, lo, hi in (
        ("notify_text_window_5h_remaining", edge_5h_lo, edge_5h_hi),
        ("notify_text_window_locking", edge_1h_lo, edge_1h_hi),
    ):
        rows = (await db.execute(
            select(models.Match).where(
                models.Match.text_state == "open",
                models.Match.lifecycle == "active",
                models.Match.call_status == "none",
                models.Match.created_at > lo,
                models.Match.created_at <= hi,
            )
        )).scalars().all()
        for m in rows:
            await _push_both_participants(db, m, push_name)
            attempted += 1
    return attempted


async def expire_unscheduled_matches(db: AsyncSession) -> int:
    """Expire locked matches whose 72h proposal window elapsed with no commitment.

    Selects matches where text_state='locked' AND lifecycle='active' AND
    call_status IN ('none','no_show') AND text_locked_at < now - 72h. For each:
    lifecycle='expired', text_state='archived'. Matches with call_status in
    {scheduled,in_progress,pending_survey,completed} are protected (they
    committed). Returns count expired.
    """
    now = utc_now()
    cutoff = now - timedelta(hours=PROPOSAL_WINDOW_HOURS)
    rows = (await db.execute(
        select(models.Match).where(
            models.Match.text_state == "locked",
            models.Match.lifecycle == "active",
            models.Match.call_status.in_(["none", "no_show"]),
            models.Match.text_locked_at < cutoff,
        )
    )).scalars().all()

    expired = 0
    for m in rows:
        try:
            m.lifecycle = "expired"
            m.text_state = "archived"
            await db.flush()
            await _push_both_participants(db, m, "notify_match_expired_unscheduled")
            expired += 1
        except Exception as exc:  # noqa: BLE001 — isolate one bad row
            logger.error("expire_unscheduled_matches failed for match %s: %s",
                         m.id, exc, exc_info=True)
            continue
    return expired


async def notify_expiring_soon_matches(db: AsyncSession) -> int:
    """Best-effort 'match_expiring_soon' push, 24h before a match expires.

    A locked/active match expires 72h after text_locked_at (the proposal window).
    "24h remaining" therefore means text_locked_at crossed the 48h-elapsed mark.
    We push to matches that are still uncommitted — call_status IN ('none',
    'no_show') — exactly as expire_unscheduled_matches selects them.

    Dedup: this runs in the 300s slow loop, so a match would otherwise satisfy a
    plain `text_locked_at < now-48h` predicate on every tick for the remaining
    24h. Mirroring notify_text_window_nudges, we restrict the fire to a single
    tick-width window: text_locked_at must have crossed the 48h threshold within
    the last tick, i.e. text_locked_at ∈ (now-48h-300s, now-48h]. Each match
    therefore fires at most once. If a tick is missed the nudge is simply skipped
    (best-effort), never re-sent. Returns the number of pushes attempted.
    """
    now = utc_now()
    tick = timedelta(seconds=300)
    # 24h-remaining: elapsed-since-lock crossed 48h within the last tick.
    edge_hi = now - timedelta(hours=PROPOSAL_WINDOW_HOURS - 24)  # 72 - 24 = 48h
    edge_lo = edge_hi - tick
    rows = (await db.execute(
        select(models.Match).where(
            models.Match.text_state == "locked",
            models.Match.lifecycle == "active",
            models.Match.call_status.in_(["none", "no_show"]),
            models.Match.text_locked_at > edge_lo,
            models.Match.text_locked_at <= edge_hi,
        )
    )).scalars().all()

    attempted = 0
    for m in rows:
        await _push_both_participants(db, m, "notify_match_expiring_soon")
        attempted += 1
    return attempted


async def detect_no_shows(db: AsyncSession) -> int:
    """Mark past scheduled calls as no_show when fewer than 2 users joined.

    Selects ScheduledCall where status='scheduled' AND
    scheduled_start_utc + 10min < now AND NOT (user1_joined AND user2_joined).
    For each, derives non-joiner ids from the join flags and calls record_no_show
    (which logs events, bumps counters, applies 2-strikes termination). Returns
    the number of calls processed.
    """
    now = utc_now()
    cutoff = now - timedelta(minutes=NO_SHOW_GRACE_MIN)
    rows = (await db.execute(
        select(models.ScheduledCall).where(
            models.ScheduledCall.status == "scheduled",
            models.ScheduledCall.scheduled_start_utc < cutoff,
            ~(models.ScheduledCall.user1_joined & models.ScheduledCall.user2_joined),
        )
    )).scalars().all()

    processed = 0
    for call in rows:
        try:
            non_joiners = []
            if not call.user1_joined:
                non_joiners.append(call.user1_id)
            if not call.user2_joined:
                non_joiners.append(call.user2_id)
            if not non_joiners:
                continue
            res = await record_no_show(db, call, non_joiners)
            # Best-effort push to both participants (terminated vs reschedule).
            m = (await db.execute(
                select(models.Match).where(models.Match.id == call.match_id)
            )).scalar_one_or_none()
            if m is not None:
                fn = ("notify_match_terminated_no_show" if res["match_terminated"]
                      else "notify_date_no_show_reschedule")
                await _push_both_participants(db, m, fn)
            processed += 1
        except Exception as exc:  # noqa: BLE001 — isolate one bad row
            logger.error("detect_no_shows failed for call %s: %s",
                         call.id, exc, exc_info=True)
            continue
    return processed


async def send_date_reminders(db: AsyncSession) -> int:
    """Push date reminders for upcoming scheduled calls (slow 300s cron).

    Two reminders per call:
    - date_starting_soon: ~15 min before start. Deduped via ScheduledCall.
      reminder_sent (set True after sending), so it fires at most once.
    - date_starting_now: at start time. Deduped to a single tick-width window
      (start within the last 300s) so the 5-min cron fires it at most once.

    Both go to both participants. Returns the number of reminders attempted.
    """
    now = utc_now()
    tick = timedelta(seconds=300)
    attempted = 0

    # --- 15-min "starting soon" reminder (dedup via reminder_sent) ----------
    soon_rows = (await db.execute(
        select(models.ScheduledCall).where(
            models.ScheduledCall.status == "scheduled",
            models.ScheduledCall.reminder_sent.is_(False),
            models.ScheduledCall.scheduled_start_utc > now,
            models.ScheduledCall.scheduled_start_utc <= now + timedelta(minutes=15),
        )
    )).scalars().all()
    for call in soon_rows:
        try:
            m = (await db.execute(
                select(models.Match).where(models.Match.id == call.match_id)
            )).scalar_one_or_none()
            if m is not None:
                await _push_both_participants(db, m, "notify_date_starting_soon", minutes=15)
                attempted += 1
            call.reminder_sent = True
            await db.flush()
        except Exception as exc:  # noqa: BLE001 — isolate one bad row
            logger.error("send_date_reminders (soon) failed for call %s: %s",
                         call.id, exc, exc_info=True)
            continue

    # --- "starting now" reminder (dedup via tick-width window) --------------
    now_rows = (await db.execute(
        select(models.ScheduledCall).where(
            models.ScheduledCall.status == "scheduled",
            models.ScheduledCall.scheduled_start_utc > now - tick,
            models.ScheduledCall.scheduled_start_utc <= now,
        )
    )).scalars().all()
    for call in now_rows:
        try:
            m = (await db.execute(
                select(models.Match).where(models.Match.id == call.match_id)
            )).scalar_one_or_none()
            if m is not None:
                await _push_both_participants(db, m, "notify_date_starting_now")
                attempted += 1
        except Exception as exc:  # noqa: BLE001 — isolate one bad row
            logger.error("send_date_reminders (now) failed for call %s: %s",
                         call.id, exc, exc_info=True)
            continue

    return attempted


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


async def unmatch(db: AsyncSession, match_id: int) -> models.Match:
    """User-initiated unmatch: terminate the match and close its conversation.

    Mirrors the lifecycle termination used by the no-show / exit-survey-no paths
    (`lifecycle='terminated'`, `text_state='archived'`) and deactivates the
    Postgres conversation so neither user surfaces for the other (see also the
    terminated-match discovery exclusion). Idempotent — a match that is already
    terminated is returned unchanged. Caller must enforce participant auth first.
    """
    m = await _lock_match(db, match_id)
    if m.lifecycle == "terminated":
        return m
    m.lifecycle = "terminated"
    m.text_state = "archived"
    conv = await _resolve_conversation_for_match(db, m)
    if conv is not None:
        conv.is_active = False
    await db.flush()
    return m


async def get_terminated_match_user_ids(db: AsyncSession, user_id: int) -> set[int]:
    """User ids the given user has a *terminated* match with (either direction).

    Used by Discover to keep unmatched users from resurfacing (and re-matching)
    regardless of which matchmaking path runs. Block uses a separate signal
    (Match.status='blocked' + a deactivated conversation) and is unaffected.
    """
    rows = (await db.execute(
        select(models.Match.user_id, models.Match.matched_user_id).where(
            models.Match.lifecycle == "terminated",
            or_(models.Match.user_id == user_id, models.Match.matched_user_id == user_id),
        )
    )).all()
    peers: set[int] = set()
    for a, b in rows:
        peers.add(b if a == user_id else a)
    return peers
