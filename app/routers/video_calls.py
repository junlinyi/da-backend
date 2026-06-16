import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional
from datetime import datetime, timedelta, timezone
import os

logger = logging.getLogger(__name__)
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VideoGrant
from twilio.rest import Client

from app.database import get_db
from app.dependencies import get_current_user
from app.models import VideoCallRoom, ScheduledCall, User, CallRating, MatchOutcome, Match
from app.services import match_state_service as mss
from app.services import push_notification_service as push
from app.schemas import (
    VideoCallTokenRequest,
    VideoCallTokenResponse,
    VideoCallRoomRequest,
    VideoCallRoomResponse,
    VideoCallRoomStatusResponse,
    CallRatingCreate,
)
from pydantic import BaseModel
from sqlalchemy import and_, or_

class CallEndRequest(BaseModel):
    actual_duration_minutes: Optional[int] = None
    ended_reason: Optional[str] = None  # e.g. "completed", "no_show", "technical"

router = APIRouter(prefix="/video-calls", tags=["video-calls"])

# Load Twilio credentials from environment variables
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_API_KEY = os.getenv("TWILIO_API_KEY")
TWILIO_API_SECRET = os.getenv("TWILIO_API_SECRET")

# Initialize Twilio client
twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_API_KEY and TWILIO_API_SECRET:
    twilio_client = Client(TWILIO_API_KEY, TWILIO_API_SECRET, TWILIO_ACCOUNT_SID)

def get_twilio_client():
    """Get Twilio client, raise error if credentials not configured"""
    if not twilio_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Twilio credentials not configured"
        )
    return twilio_client


# ── Scheduling V2 lifecycle helpers (Phase 8) ────────────────────────────────
#
# These hook the V2 call_status state machine into the existing Twilio video
# endpoints. They are additive: Twilio is reused as-is.

async def _v2_mark_joined_and_maybe_start(
    db: AsyncSession, call: ScheduledCall, joining_user_id: int
) -> bool:
    """Mark the joining user's join flag. When BOTH users are now present AND the
    match is still 'scheduled', transition the match to 'in_progress', stamp the
    call started, and increment total_calls_completed for BOTH users exactly once.

    Idempotency: the in_progress transition + counter bumps only happen on the
    scheduled->in_progress edge (guarded on match.call_status == 'scheduled'
    BEFORE transitioning), so re-joining an already-in-progress call is a no-op.

    Returns True if the scheduled->in_progress transition fired this call.
    Does NOT commit — the caller owns the transaction.
    """
    if joining_user_id == call.user1_id:
        call.user1_joined = True
    elif joining_user_id == call.user2_id:
        call.user2_joined = True

    if not (call.user1_joined and call.user2_joined):
        return False

    # Load the match to check the guard BEFORE transitioning (idempotency).
    match = (await db.execute(
        select(Match).where(Match.id == call.match_id)
    )).scalars().first()
    if match is None or match.call_status != "scheduled":
        return False

    await mss.transition_call_status(db, call.match_id, "in_progress")
    call.status = "in_progress"
    if call.call_started_at is None:
        call.call_started_at = mss.utc_now()

    # Increment total_calls_completed for both participants exactly once.
    for uid in (call.user1_id, call.user2_id):
        u = (await db.execute(
            select(User).where(User.id == uid)
        )).scalars().first()
        if u is not None:
            u.total_calls_completed = (u.total_calls_completed or 0) + 1
    return True


async def _v2_mark_ended_and_prompt_survey(db: AsyncSession, call: ScheduledCall) -> bool:
    """On a normal call completion, transition the match in_progress->pending_survey
    and fire the exit-survey prompt (push to both + system message). Best-effort on
    the prompt side. No-op (returns False) if the match isn't 'in_progress'.

    Does NOT commit — the caller owns the transaction.
    """
    match = (await db.execute(
        select(Match).where(Match.id == call.match_id)
    )).scalars().first()
    if match is None or match.call_status != "in_progress":
        return False

    await mss.transition_call_status(db, call.match_id, "pending_survey")

    # Best-effort: push both participants + system message. Never break the txn.
    try:
        user_a = (await db.execute(
            select(User).where(User.id == match.user_id)
        )).scalars().first()
        user_b = (await db.execute(
            select(User).where(User.id == match.matched_user_id)
        )).scalars().first()
        for recipient, peer in ((user_a, user_b), (user_b, user_a)):
            if recipient is None:
                continue
            peer_name = (peer.name if peer else None) or "your match"
            await push.notify_exit_survey_prompt(
                recipient=recipient, peer_name=peer_name, match_id=match.id
            )
        await mss.write_system_message(
            db, match, "exit_survey_prompt",
            "How was your video date? Tap to let us know.",
        )
    except Exception as exc:  # noqa: BLE001 — best-effort prompt
        logger.warning("exit_survey_prompt best-effort failed for match %s: %s",
                       match.id, exc)
    return True


@router.post("/token", response_model=VideoCallTokenResponse)
async def generate_video_call_token(
    request: VideoCallTokenRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate Twilio access token for joining a video call room.
    """
    # Verify Twilio is configured
    if not TWILIO_ACCOUNT_SID or not TWILIO_API_KEY or not TWILIO_API_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Twilio credentials not configured"
        )

    # Create access token
    token = AccessToken(
        TWILIO_ACCOUNT_SID,
        TWILIO_API_KEY,
        TWILIO_API_SECRET,
        identity=request.user_identity
    )

    # Grant access to video
    video_grant = VideoGrant(room=request.room_name)
    token.add_grant(video_grant)

    # Token TTL: 2 hours gives comfortable headroom for any scheduled call
    # (BE-10 fix: was hardcoded 3600 = 1 hour, which breaks calls > 1h)
    token.ttl = 7200

    return VideoCallTokenResponse(
        token=token.to_jwt(),
        room_name=request.room_name
    )


@router.post("/rooms", response_model=VideoCallRoomResponse)
async def create_or_get_video_call_room(
    request: VideoCallRoomRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create or get existing video call room for a scheduled call.
    """
    user_id = current_user.id

    # Verify scheduled call exists and user is part of it
    result = await db.execute(
        select(ScheduledCall).where(ScheduledCall.id == request.call_id)
    )
    scheduled_call = result.scalars().first()

    if not scheduled_call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled call not found"
        )

    # Verify user is part of the scheduled call
    if scheduled_call.user1_id != user_id and scheduled_call.user2_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this call"
        )

    # ── Phase 8 (Task 8.1): hitting this endpoint == joining the call.
    # Mark the join flag and, when both are present for the first time, flip the
    # match to in_progress + bump total_calls_completed. Idempotent.
    await _v2_mark_joined_and_maybe_start(db, scheduled_call, user_id)

    # Check if room already exists
    result = await db.execute(
        select(VideoCallRoom).where(VideoCallRoom.scheduled_call_id == request.call_id)
    )
    existing_room = result.scalars().first()

    if existing_room:
        await db.commit()
        return VideoCallRoomResponse(
            room_name=existing_room.room_name,
            room_sid=existing_room.room_sid,
            status=existing_room.status
        )

    # Create new room
    room_name = f"call_{request.call_id}"

    new_room = VideoCallRoom(
        scheduled_call_id=request.call_id,
        room_name=room_name,
        status="active"
    )

    db.add(new_room)
    await db.commit()
    await db.refresh(new_room)

    return VideoCallRoomResponse(
        room_name=new_room.room_name,
        room_sid=new_room.room_sid,
        status=new_room.status
    )


@router.get("/rooms/{room_name}/status", response_model=VideoCallRoomStatusResponse)
async def get_room_status(
    room_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get status of a video call room.
    """
    result = await db.execute(
        select(VideoCallRoom).where(VideoCallRoom.room_name == room_name)
    )
    room = result.scalars().first()

    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found"
        )

    # Verify user is part of the scheduled call
    result = await db.execute(
        select(ScheduledCall).where(ScheduledCall.id == room.scheduled_call_id)
    )
    scheduled_call = result.scalars().first()

    if not scheduled_call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled call not found"
        )

    user_id = current_user.id
    if scheduled_call.user1_id != user_id and scheduled_call.user2_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this room"
        )

    return VideoCallRoomStatusResponse(
        room_name=room.room_name,
        room_sid=room.room_sid,
        status=room.status,
        created_at=room.created_at,
        ended_at=room.ended_at
    )


@router.post("/rooms/{room_name}/end")
async def end_room(
    room_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    End a video call room.
    """
    result = await db.execute(
        select(VideoCallRoom).where(VideoCallRoom.room_name == room_name)
    )
    room = result.scalars().first()

    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found"
        )

    # Verify user is part of the scheduled call
    result = await db.execute(
        select(ScheduledCall).where(ScheduledCall.id == room.scheduled_call_id)
    )
    scheduled_call = result.scalars().first()

    if not scheduled_call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled call not found"
        )

    user_id = current_user.id
    if scheduled_call.user1_id != user_id and scheduled_call.user2_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to end this room"
        )

    # Update room status
    room.status = "ended"
    room.ended_at = datetime.now(timezone.utc)

    await db.commit()

    return {"message": "Room ended successfully"}


# ── BE-02: Call end endpoint ─────────────────────────────────────────────────

@router.post("/{call_id}/end")
async def end_call(
    call_id: int,
    body: CallEndRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Record that a scheduled call has ended.

    - Updates call status to "completed" (or "no_show" / "cancelled" via ended_reason)
    - Stores actual_duration_minutes for ML feature computation
    - Force-closes the Twilio room
    - Records call_completed_at on the MatchOutcome for ML training
    """
    call_q = await db.execute(select(ScheduledCall).where(ScheduledCall.id == call_id))
    call = call_q.scalars().first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    if call.user1_id != current_user.id and call.user2_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your call")

    now = datetime.now(timezone.utc)
    call.call_ended_at = now
    call.actual_duration_minutes = body.actual_duration_minutes

    # Determine final status from ended_reason
    reason = (body.ended_reason or "completed").lower()
    if reason in ("no_show",):
        call.status = "no_show"
    elif reason in ("cancelled", "cancel"):
        call.status = "cancelled"
    else:
        call.status = "completed"

    # Close the Twilio room if one exists
    room_q = await db.execute(
        select(VideoCallRoom).where(VideoCallRoom.scheduled_call_id == call_id)
    )
    room = room_q.scalars().first()
    if room and room.status == "active":
        room.status = "ended"
        room.ended_at = now
        client = get_twilio_client()
        try:
            client.video.v1.rooms(room.room_name).update(status="completed")
        except Exception as exc:
            logger.warning(f"Twilio room close failed for {room.room_name}: {exc}")

    # Update MatchOutcome for ML training
    outcome_q = await db.execute(
        select(MatchOutcome).where(MatchOutcome.match_id == call.match_id)
    )
    outcome = outcome_q.scalars().first()
    if outcome and call.status == "completed":
        if outcome.call_completed_at is None:
            outcome.call_completed_at = now

    # ── Phase 8 (Task 8.2): on a normal completion (NOT no_show/cancelled),
    # advance the match in_progress->pending_survey and fire the exit survey.
    # no_show/cancelled are left to the no-show flow.
    if call.status == "completed":
        await _v2_mark_ended_and_prompt_survey(db, call)

    await db.commit()
    return {"message": f"Call {call_id} ended", "status": call.status}


# ── Phase 8: Debug E2E driver ────────────────────────────────────────────────


class DebugAdvanceRequest(BaseModel):
    action: str  # "join_both" | "end"


def _debug_endpoints_enabled() -> bool:
    """Debug endpoints are available everywhere EXCEPT production."""
    if os.getenv("ENABLE_DEBUG_ENDPOINTS", "").lower() in ("1", "true", "yes"):
        return True
    return os.getenv("ENVIRONMENT", "development").lower() != "production"


@router.post("/{call_id}/debug-advance")
async def debug_advance_call(
    call_id: int,
    body: DebugAdvanceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Debug-only: drive the V2 call lifecycle without real Twilio media, so the
    iOS sim E2E can advance a call through in_progress -> pending_survey.

    Gated to non-production environments (or ENABLE_DEBUG_ENDPOINTS).

    - action="join_both": set both join flags, transition to in_progress, bump
      total_calls_completed (reuses the Task 8.1 join logic).
    - action="end": transition in_progress -> pending_survey + fire the exit
      survey prompt (reuses the Task 8.2 end logic).
    """
    if not _debug_endpoints_enabled():
        raise HTTPException(status_code=404, detail="Not found")

    call_q = await db.execute(select(ScheduledCall).where(ScheduledCall.id == call_id))
    call = call_q.scalars().first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    if call.user1_id != current_user.id and call.user2_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your call")

    action = (body.action or "").lower()
    if action == "join_both":
        call.user1_joined = True
        # Run the shared join logic for the second user; both flags now True so
        # it evaluates the scheduled->in_progress edge.
        started = await _v2_mark_joined_and_maybe_start(db, call, call.user2_id)
        await db.commit()
        return {"message": "join_both applied", "started": started,
                "call_status": "in_progress" if started else None}
    elif action == "end":
        ended = await _v2_mark_ended_and_prompt_survey(db, call)
        if ended:
            call.status = "completed"
            if call.call_ended_at is None:
                call.call_ended_at = mss.utc_now()
        await db.commit()
        return {"message": "end applied", "advanced": ended,
                "call_status": "pending_survey" if ended else None}
    else:
        raise HTTPException(status_code=400, detail="action must be 'join_both' or 'end'")


# ── BE-01: Call rating endpoint ──────────────────────────────────────────────

@router.post("/{call_id}/rate")
async def rate_call(
    call_id: int,
    body: CallRatingCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a post-call rating (1–5 stars) for the other participant.

    - Writes to call_ratings (one per rater per call, enforced by DB constraint)
    - Updates MatchOutcome.user{1,2}_call_rating and avg_call_rating
    """
    call_q = await db.execute(select(ScheduledCall).where(ScheduledCall.id == call_id))
    call = call_q.scalars().first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    if call.user1_id != current_user.id and call.user2_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your call")
    if call.status not in ("completed",):
        raise HTTPException(status_code=400, detail="Can only rate completed calls")

    # Determine who is being rated
    rated_user_id = call.user2_id if call.user1_id == current_user.id else call.user1_id

    # Upsert the rating (unique constraint: call_id + rater_id)
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    existing_q = await db.execute(
        select(CallRating).where(
            CallRating.call_id == call_id,
            CallRating.rater_id == current_user.id,
        )
    )
    existing = existing_q.scalars().first()
    if existing:
        existing.rating = body.rating
        existing.feedback = body.feedback
        existing.categories = body.categories
    else:
        new_rating = CallRating(
            call_id=call_id,
            rater_id=current_user.id,
            rated_user_id=rated_user_id,
            rating=body.rating,
            feedback=body.feedback,
            categories=body.categories,
        )
        db.add(new_rating)

    # Update MatchOutcome quality signals
    outcome_q = await db.execute(
        select(MatchOutcome).where(MatchOutcome.match_id == call.match_id)
    )
    outcome = outcome_q.scalars().first()
    if outcome:
        if current_user.id == call.user1_id:
            outcome.user1_call_rating = body.rating
        else:
            outcome.user2_call_rating = body.rating
        # Recompute avg using available ratings
        ratings = [r for r in [outcome.user1_call_rating, outcome.user2_call_rating] if r is not None]
        outcome.avg_call_rating = sum(ratings) / len(ratings) if ratings else None

    await db.commit()
    return {"message": "Rating submitted", "call_id": call_id, "rating": body.rating}
