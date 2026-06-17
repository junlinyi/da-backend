"""
Push notification service.

All public functions silently no-op (log a warning) when the recipient has no
device_token, so callers never need to guard against None tokens.

Sending uses Firebase Cloud Messaging (FCM) via the firebase-admin SDK, which
forwards to APNs for iOS devices.  The firebase_admin app must be initialized
before any function here is called (guaranteed by app/firebase.py being
imported at startup).
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core send helper
# ---------------------------------------------------------------------------

async def send_push(
    token: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> bool:
    """
    Send a single push notification via FCM.

    Returns True on success, False on failure.  Never raises.
    """
    try:
        from firebase_admin import messaging

        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            token=token,
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default", badge=1)
                )
            ),
        )
        messaging.send(message)
        logger.info(f"[PUSH] Sent '{title}' to token ending …{token[-6:]}")
        return True
    except Exception as exc:
        logger.warning(f"[PUSH] Failed to send '{title}': {exc}")
        return False


def _push_enabled(user) -> bool:
    """
    Returns True if the user should receive push notifications.

    Checks two conditions:
    1. The user has a registered device token.
    2. The user has not opted out via UserSchedulingPreferences.push_notifications.

    The scheduling_preferences relationship must be loaded on the user object
    before calling this (either via eager load or lazy access in a sync context).
    If the relationship is None (no prefs row yet), notifications are sent by default.
    """
    if not user.device_token:
        return False
    prefs = getattr(user, "scheduling_preferences", None)
    if prefs is not None and not prefs.push_notifications:
        return False
    return True


def _no_token(user_name: str, notification_type: str) -> None:
    logger.warning(
        f"[PUSH] Skipping {notification_type} for {user_name} — no device_token or notifications disabled"
    )


# ---------------------------------------------------------------------------
# Typed notification functions
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Scheduling V2 — typed senders (Task 7.1)
#
# Copy is taken from DatingAppProj/NOTIFICATIONS.md (canonical taxonomy) /
# SCHEDULING_V2.md §Push Notifications. All user-facing copy says "video date".
# `data.type` matches the V2 notification id so the iOS NotificationRouter can
# route. Every sender no-ops when _push_enabled() is False.
# ---------------------------------------------------------------------------


def _name(user) -> str:
    return (getattr(user, "name", None) or "Someone")


async def notify_new_match(recipient, matcher_name: str, match_id: int) -> None:
    """D1 — Person who was swiped on gets notified of a new match."""
    if not _push_enabled(recipient):
        _no_token(recipient.name or "?", "new_match")
        return
    await send_push(
        token=recipient.device_token,
        title="It's a match!",
        body=f"You and {matcher_name} both liked each other. Schedule a call within 48 hours!",
        data={
            "type": "new_match",
            "matcher_name": matcher_name,
            "match_id": match_id,
        },
    )


async def notify_new_message(recipient, sender_name: str, conversation_id: int, preview: str) -> None:
    """D2 — Message recipient gets notified of a new chat message."""
    if not _push_enabled(recipient):
        _no_token(recipient.name or "?", "new_message")
        return

    # Truncate preview to avoid excessively long notification bodies
    if len(preview) > 80:
        preview = preview[:77] + "…"

    await send_push(
        token=recipient.device_token,
        title=sender_name,
        body=preview,
        data={
            "type": "new_message",
            "sender_name": sender_name,
            "conversation_id": conversation_id,
        },
    )


# ===========================================================================
# Scheduling V2 — the 16 typed senders (Task 7.1)
#
# Each takes the recipient User + context (peer_name, match_id, …).
# Copy from DatingAppProj/NOTIFICATIONS.md / SCHEDULING_V2.md §Push
# Notifications. "video date" everywhere. data.type == the V2 notification id.
# ===========================================================================


# --- Texting-window nudges + lock (cron-triggered) -------------------------

async def notify_text_window_5h_remaining(recipient, peer_name: str, match_id: int) -> None:
    """5h before the 24h text lock, no date scheduled. (Nudge 1 of 2.)"""
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "text_window_5h_remaining")
        return
    await send_push(
        token=recipient.device_token,
        title="Schedule your video date",
        body=f"5 hours of free chat left with {peer_name}. Schedule your video date.",
        data={"type": "text_window_5h_remaining", "match_id": match_id, "peer_name": peer_name},
    )


async def notify_text_window_locking(recipient, peer_name: str, match_id: int) -> None:
    """1h before the 24h text lock, no date scheduled. (Nudge 2 of 2.)"""
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "text_window_locking")
        return
    await send_push(
        token=recipient.device_token,
        title="Text pauses in 1 hour",
        body=f"Text with {peer_name} pauses in 1 hour. Schedule your video date.",
        data={"type": "text_window_locking", "match_id": match_id, "peer_name": peer_name},
    )


async def notify_text_locked(recipient, peer_name: str, match_id: int) -> None:
    """At the 24h text lock with no date scheduled."""
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "text_locked")
        return
    await send_push(
        token=recipient.device_token,
        title="Text paused",
        body=f"Text with {peer_name} is paused. Schedule your video date to continue.",
        data={"type": "text_locked", "match_id": match_id, "peer_name": peer_name},
    )


# --- Proposal lifecycle (endpoint-triggered) -------------------------------

async def notify_proposal_received(recipient, peer_name: str, match_id: int, when: str = "") -> None:
    """The non-proposer is notified a video date was proposed.

    `when` is a pre-formatted human date+time string (e.g. "Thu 8 PM").
    """
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "proposal_received")
        return
    when_suffix = f" for {when}" if when else ""
    await send_push(
        token=recipient.device_token,
        title="New video date proposed",
        body=f"{peer_name} proposed a video date{when_suffix}. Open the app to review.",
        data={"type": "proposal_received", "match_id": match_id, "peer_name": peer_name},
    )


async def notify_proposal_accepted(recipient, peer_name: str, match_id: int, when: str = "") -> None:
    """The original proposer is notified their proposal was accepted."""
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "proposal_accepted")
        return
    when_suffix = f" See you {when}." if when else ""
    await send_push(
        token=recipient.device_token,
        title="Video date confirmed!",
        body=f"{peer_name} accepted your video date!{when_suffix}",
        data={"type": "proposal_accepted", "match_id": match_id, "peer_name": peer_name},
    )


async def notify_counter_proposal_received(recipient, peer_name: str, match_id: int, when: str = "") -> None:
    """The original proposer is notified of a counter-proposed time."""
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "counter_proposal_received")
        return
    when_suffix = f": {when}" if when else ""
    await send_push(
        token=recipient.device_token,
        title="A different video date time",
        body=f"{peer_name} proposed a different time{when_suffix}. Review and accept?",
        data={"type": "counter_proposal_received", "match_id": match_id, "peer_name": peer_name},
    )


# --- Match expiry (cron-triggered) -----------------------------------------

async def notify_match_expiring_soon(recipient, peer_name: str, match_id: int) -> None:
    """24h before the match expires with no scheduled date."""
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "match_expiring_soon")
        return
    await send_push(
        token=recipient.device_token,
        title="Your match is expiring",
        body=f"Your match with {peer_name} expires in 24 hours. Schedule your video date.",
        data={"type": "match_expiring_soon", "match_id": match_id, "peer_name": peer_name},
    )


async def notify_match_expired_unscheduled(recipient, peer_name: str, match_id: int) -> None:
    """72h post-lock elapsed without scheduling — match expired."""
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "match_expired_unscheduled")
        return
    await send_push(
        token=recipient.device_token,
        title="Your match expired",
        body=(
            f"Your match with {peer_name} expired. "
            "Schedule a video date within 72 hours next time."
        ),
        data={"type": "match_expired_unscheduled", "match_id": match_id, "peer_name": peer_name},
    )


# --- Date timing reminders (cron-triggered) --------------------------------

async def notify_date_starting_soon(recipient, peer_name: str, match_id: int, minutes: int = 15) -> None:
    """15 min before the scheduled date start."""
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "date_starting_soon")
        return
    await send_push(
        token=recipient.device_token,
        title="Your video date is soon",
        body=f"Your video date with {peer_name} starts in {minutes} minutes.",
        data={"type": "date_starting_soon", "match_id": match_id, "peer_name": peer_name},
    )


async def notify_date_starting_now(recipient, peer_name: str, match_id: int) -> None:
    """At the scheduled date start time."""
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "date_starting_now")
        return
    await send_push(
        token=recipient.device_token,
        title="Your video date is starting",
        body=f"Your video date with {peer_name} is starting. Tap to join.",
        data={"type": "date_starting_now", "match_id": match_id, "peer_name": peer_name},
    )


# --- No-show outcomes (endpoint + cron triggered) --------------------------

async def notify_date_no_show_reschedule(recipient, peer_name: str, match_id: int) -> None:
    """After no-show #1 on this match (match NOT terminated)."""
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "date_no_show_reschedule")
        return
    await send_push(
        token=recipient.device_token,
        title="Missed video date",
        body=f"{peer_name} missed your video date. Reschedule when ready.",
        data={"type": "date_no_show_reschedule", "match_id": match_id, "peer_name": peer_name},
    )


async def notify_match_terminated_no_show(recipient, peer_name: str, match_id: int) -> None:
    """After no-show #2 by the same user on this match — match terminated."""
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "match_terminated_no_show")
        return
    await send_push(
        token=recipient.device_token,
        title="Match ended",
        body=f"Your match with {peer_name} ended after missed video dates.",
        data={"type": "match_terminated_no_show", "match_id": match_id, "peer_name": peer_name},
    )


# --- Exit-survey outcomes (endpoint-triggered) -----------------------------

async def notify_exit_survey_prompt(recipient, peer_name: str, match_id: int) -> None:
    """The video date ended — prompt both users for the exit survey."""
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "exit_survey_prompt")
        return
    await send_push(
        token=recipient.device_token,
        title="How was your video date?",
        body=f"How was your video date with {peer_name}? Tap to respond.",
        data={"type": "exit_survey_prompt", "match_id": match_id, "peer_name": peer_name},
    )


async def notify_partner_responded_yes(recipient, peer_name: str, match_id: int) -> None:
    """One user said yes on the exit survey; the non-responder is nudged."""
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "partner_responded_yes")
        return
    await send_push(
        token=recipient.device_token,
        title="Keep talking?",
        body=f"{peer_name} wants to keep talking. Tap to respond.",
        data={"type": "partner_responded_yes", "match_id": match_id, "peer_name": peer_name},
    )


async def notify_text_unlocked_mutual_yes(recipient, peer_name: str, match_id: int) -> None:
    """Both users said yes on the exit survey — chat reopens, contact unlocked."""
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "text_unlocked_mutual_yes")
        return
    await send_push(
        token=recipient.device_token,
        title="It's mutual!",
        body=(
            f"{peer_name} also wants to keep talking. "
            "Chat is open and you can now share contact info."
        ),
        data={"type": "text_unlocked_mutual_yes", "match_id": match_id, "peer_name": peer_name},
    )


async def notify_match_terminated_survey_no(recipient, peer_name: str, match_id: int, is_no_er: bool) -> None:
    """Either user said no on the exit survey — asymmetric copy.

    To the user who said no (`is_no_er=True`): a clean acknowledgement.
    To the other user: a softer "not a mutual match" message (no blame).
    """
    if not _push_enabled(recipient):
        _no_token(_name(recipient), "match_terminated_survey_no")
        return
    if is_no_er:
        title = "Match ended"
        body = "Got it — we've ended this match."
    else:
        title = "Not a match this time"
        body = "It wasn't a mutual match this time."
    await send_push(
        token=recipient.device_token,
        title=title,
        body=body,
        data={"type": "match_terminated_survey_no", "match_id": match_id, "peer_name": peer_name},
    )
