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

async def notify_immediate_call_request(recipient, caller, call_id: int) -> None:
    """S1 — User B gets notified when User A taps 'Call Now'."""
    if not _push_enabled(recipient):
        _no_token(recipient.name or "?", "immediate_call_request")
        return
    await send_push(
        token=recipient.device_token,
        title=f"{caller.name or 'Someone'} wants to call now!",
        body="They're available right now for a 15-min video call. Tap to join.",
        data={
            "type": "immediate_call_request",
            "caller_name": caller.name or "",
            "call_id": call_id,
        },
    )


async def notify_proposal_received(recipient, proposer, proposal_id: int) -> None:
    """S2 — User B gets notified when User A submits a Tier 2 proposal."""
    if not _push_enabled(recipient):
        _no_token(recipient.name or "?", "proposal_received")
        return
    await send_push(
        token=recipient.device_token,
        title=f"{proposer.name or 'Someone'} proposed call times",
        body="They suggested a few time windows. Pick the one that works for you.",
        data={
            "type": "proposal_received",
            "proposer_name": proposer.name or "",
            "proposal_id": proposal_id,
        },
    )


async def notify_proposal_accepted(proposer, accepter, call_id: int) -> None:
    """S3 — User A gets notified when User B accepts their proposal."""
    if not _push_enabled(proposer):
        _no_token(proposer.name or "?", "proposal_accepted")
        return
    await send_push(
        token=proposer.device_token,
        title=f"{accepter.name or 'Someone'} accepted your proposal!",
        body="Your call is now scheduled. Check your upcoming calls.",
        data={
            "type": "proposal_accepted",
            "accepter_name": accepter.name or "",
            "call_id": call_id,
        },
    )


async def notify_proposal_rejected(proposer, rejecter) -> None:
    """S4 — User A gets notified when User B rejects their proposal."""
    if not _push_enabled(proposer):
        _no_token(proposer.name or "?", "proposal_rejected")
        return
    await send_push(
        token=proposer.device_token,
        title=f"{rejecter.name or 'Someone'} passed on your times",
        body="They couldn't make those times work. You can propose new ones.",
        data={
            "type": "proposal_rejected",
            "rejecter_name": rejecter.name or "",
        },
    )


async def notify_counter_proposal_received(recipient, proposer, proposal_id: int) -> None:
    """S9 — Original proposer gets notified of a counter-proposal."""
    if not _push_enabled(recipient):
        _no_token(recipient.name or "?", "counter_proposal_received")
        return
    await send_push(
        token=recipient.device_token,
        title=f"{proposer.name or 'Someone'} suggested different times",
        body="They proposed new time windows. Pick one to confirm your call.",
        data={
            "type": "proposal_received",
            "proposer_name": proposer.name or "",
            "proposal_id": proposal_id,
        },
    )


async def notify_call_reminder(user, call, minutes_before: int) -> None:
    """S5/S6 — Remind both users before a scheduled call."""
    if not _push_enabled(user):
        _no_token(user.name or "?", f"call_reminder_{minutes_before}min")
        return

    if minutes_before >= 60:
        title = "Call starting in 1 hour"
        body = "Your 15-min video call is coming up. Get ready!"
    else:
        title = f"Call starting in {minutes_before} minutes"
        body = "Your video call is almost here. Tap to join when ready."

    await send_push(
        token=user.device_token,
        title=title,
        body=body,
        data={
            "type": "call_reminder",
            "call_id": call.id,
            "minutes_before": minutes_before,
        },
    )


async def notify_match_expiring(user, match_name: str, hours_left: int) -> None:
    """S7 — Both users notified when the 48h scheduling window is almost closed."""
    if not _push_enabled(user):
        _no_token(user.name or "?", "match_expiring")
        return
    await send_push(
        token=user.device_token,
        title=f"Schedule your call with {match_name}!",
        body=f"Only {hours_left} hours left to schedule your 15-min call before the match expires.",
        data={
            "type": "match_expiring",
            "match_name": match_name,
            "hours_left": hours_left,
        },
    )


async def notify_availability_match(user1, user2, slot_count: int) -> None:
    """S8 — Both users notified when common availability is found."""
    for user, other in [(user1, user2), (user2, user1)]:
        if not _push_enabled(user):
            _no_token(user.name or "?", "availability_match")
            continue
        await send_push(
            token=user.device_token,
            title=f"You and {other.name or 'your match'} are both free!",
            body=(
                f"You have {slot_count} time slot{'s' if slot_count != 1 else ''} in common "
                "this week. Schedule your call now!"
            ),
            data={
                "type": "availability_match",
                "match_name": other.name or "",
                "slot_count": slot_count,
            },
        )


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


async def notify_no_show_partner(waiting_user, absent_name: str, call_id: int) -> None:
    """Notify a user that their match did not join the scheduled call."""
    if not _push_enabled(waiting_user):
        _no_token(waiting_user.name or "?", "no_show_partner")
        return
    await send_push(
        token=waiting_user.device_token,
        title="Your match didn't show up",
        body=f"{absent_name} didn't join your video call. We've noted this on their account.",
        data={
            "type": "no_show_partner",
            "absent_name": absent_name,
            "call_id": call_id,
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
