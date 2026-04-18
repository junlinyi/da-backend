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
from app.models import VideoCallRoom, ScheduledCall, User, CallRating, MatchOutcome
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

    # Check if room already exists
    result = await db.execute(
        select(VideoCallRoom).where(VideoCallRoom.scheduled_call_id == request.call_id)
    )
    existing_room = result.scalars().first()

    if existing_room:
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

    await db.commit()
    return {"message": f"Call {call_id} ended", "status": call.status}


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
