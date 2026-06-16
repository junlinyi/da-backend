# app/routers/scheduling.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime, time, timedelta, timezone
from app.database import get_db
from app.models import (
    User, UserSchedulingPreferences, ScheduledCall, Match,
    MatchOutcome, VideoCallProposal
)
# NOTE(v2): Legacy proposal/call-request models and the Tier-1/direct-create
# endpoints that referenced them (SchedulingProposal, ProposalTimeSlot,
# ProposalResponse, CounterProposalTimeSlot, CallRequest, plus schedule_call /
# extend_call / confirm_call) were removed in Task 9.1. V2 calls are created via
# the propose/accept/counter flow below, never by direct POST /calls.
from app import schemas
from app.schemas import (
    UserSchedulingPreferenceCreate, UserSchedulingPreferenceResponse,
    ScheduledCallResponse,
    ProposeCallRequest, CounterProposalRequest, VideoCallProposalResponse,
)
from app.services import match_state_service as mss
from app.dependencies import verify_firebase_token, get_current_user
import logging
import traceback
import firebase_admin
from firebase_admin import auth as firebase_auth
from app.services import push_notification_service as push

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure Firebase Admin is initialized
if not firebase_admin._apps:
    firebase_admin.initialize_app()

router = APIRouter()


# ============================================================================
# SCHEDULING PREFERENCES ENDPOINTS
# ============================================================================

@router.get("/me/preferences", response_model=UserSchedulingPreferenceResponse)
async def get_scheduling_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's scheduling preferences"""
    result = await db.execute(
        select(UserSchedulingPreferences).where(UserSchedulingPreferences.user_id == user.id)
    )
    preferences = result.scalar_one_or_none()
    
    if not preferences:
        # Return default preferences
        return UserSchedulingPreferenceResponse(
            user_id=user.id,
            max_calls_per_week=5,
            min_notice_hours=2,
            max_advance_days=7,
            preferred_start_time=time(18, 0),
            preferred_end_time=time(22, 0),
            email_notifications=True,
            push_notifications=True,
            reminder_hours_before=1
        )
    
    return preferences

@router.put("/me/preferences", response_model=UserSchedulingPreferenceResponse)
async def update_scheduling_preferences(
    preferences_data: UserSchedulingPreferenceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user's scheduling preferences"""
    result = await db.execute(
        select(UserSchedulingPreferences).where(UserSchedulingPreferences.user_id == user.id)
    )
    preferences = result.scalar_one_or_none()
    
    if not preferences:
        # Create new preferences record
        preferences = UserSchedulingPreferences(
            user_id=user.id,
            max_calls_per_week=preferences_data.max_calls_per_week,
            min_notice_hours=preferences_data.min_notice_hours,
            max_advance_days=preferences_data.max_advance_days,
            preferred_start_time=preferences_data.preferred_start_time,
            preferred_end_time=preferences_data.preferred_end_time,
            email_notifications=preferences_data.email_notifications,
            push_notifications=preferences_data.push_notifications,
            reminder_hours_before=preferences_data.reminder_hours_before
        )
        db.add(preferences)
    else:
        # Update existing preferences
        preferences.max_calls_per_week = preferences_data.max_calls_per_week
        preferences.min_notice_hours = preferences_data.min_notice_hours
        preferences.max_advance_days = preferences_data.max_advance_days
        preferences.preferred_start_time = preferences_data.preferred_start_time
        preferences.preferred_end_time = preferences_data.preferred_end_time
        preferences.email_notifications = preferences_data.email_notifications
        preferences.push_notifications = preferences_data.push_notifications
        preferences.reminder_hours_before = preferences_data.reminder_hours_before
        preferences.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(preferences)
    
    logger.info(f"Updated scheduling preferences for user {user.id}")
    return preferences

# ============================================================================
# VIDEO CALL ENDPOINTS
# ============================================================================

@router.get("/me/calls", response_model=List[ScheduledCallResponse])
async def get_my_calls(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None, description="Filter by call status"),
    upcoming: bool = Query(True, description="Get upcoming calls (True) or past calls (False)")
):
    """Get user's scheduled calls with user names"""
    query = select(ScheduledCall).where(
        (ScheduledCall.user1_id == user.id) | (ScheduledCall.user2_id == user.id)
    )
    
    if status:
        query = query.where(ScheduledCall.status == status)
    
    if upcoming:
        # Show calls that haven't ended yet (covers both future and currently-active calls)
        query = query.where(ScheduledCall.scheduled_end_utc >= datetime.now(timezone.utc))
    else:
        query = query.where(ScheduledCall.scheduled_end_utc < datetime.now(timezone.utc))
    
    query = query.order_by(ScheduledCall.scheduled_start_utc)
    result = await db.execute(query)
    
    # Process results to populate user names and determine "other" user
    calls = []
    for row in result.all():
        call = row[0]  # ScheduledCall object
        
        # Get both user names
        user1_query = await db.execute(select(User).where(User.id == call.user1_id))
        user1 = user1_query.scalar_one_or_none()
        
        user2_query = await db.execute(select(User).where(User.id == call.user2_id))
        user2 = user2_query.scalar_one_or_none()
        
        # Determine which is the "other" user
        if call.user1_id == user.id:
            other_user_name = user2.name if user2 else "Unknown User"
            other_user_id = call.user2_id
            other_user_firebase_uid = user2.firebase_uid if user2 else None
        else:
            other_user_name = user1.name if user1 else "Unknown User"
            other_user_id = call.user1_id
            other_user_firebase_uid = user1.firebase_uid if user1 else None

        # Format datetime for iOS
        start_time_str = call.scheduled_start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_time_str = call.scheduled_end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        created_str = call.created_at.strftime('%Y-%m-%dT%H:%M:%SZ')
        updated_str = call.updated_at.strftime('%Y-%m-%dT%H:%M:%SZ')

        # Create response object with populated names
        call_response = ScheduledCallResponse(
            id=call.id,
            user_id=user.id,  # iOS compatibility
            match_id=call.match_id,
            user1_id=call.user1_id,
            user2_id=call.user2_id,
            user1_name=user1.name if user1 else None,
            user2_name=user2.name if user2 else None,
            other_user_name=other_user_name,
            other_user_id=other_user_id,
            other_user_firebase_uid=other_user_firebase_uid,
            start_time_utc=start_time_str,  # iOS expects string
            end_time_utc=end_time_str,      # iOS expects string
            scheduled_start_utc=call.scheduled_start_utc,
            scheduled_end_utc=call.scheduled_end_utc,
            duration_minutes=call.duration_minutes,
            status=call.status,
            user1_confirmed=call.user1_confirmed,
            user2_confirmed=call.user2_confirmed,
            user1_confirmed_at=call.user1_confirmed_at,
            user2_confirmed_at=call.user2_confirmed_at,
            call_room_id=call.call_room_id,
            call_started_at=call.call_started_at,
            call_ended_at=call.call_ended_at,
            actual_duration_minutes=call.actual_duration_minutes,
            original_call_id=call.original_call_id,
            reschedule_count=call.reschedule_count,
            user1_notified=call.user1_notified,
            user2_notified=call.user2_notified,
            reminder_sent=call.reminder_sent,
            created_at=call.created_at,
            updated_at=call.updated_at
        )
        calls.append(call_response)
    
    return calls

@router.get("/me/matches", response_model=List[schemas.MatchListItem])
async def get_my_matches(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Scheduling V2 — return the viewer's ACTIVE matches with the full state
    triplet (text_state / call_status / lifecycle), a precomputed card_display
    string, the active proposal (if any), the current scheduled call (if any),
    and exit-survey responses.

    Spec: DatingAppProj/SCHEDULING_V2.md §Endpoints (me/matches) +
    §valid-combinations (card_display) + §Transition rules (proposer-waiting copy).
    """
    matches = (
        await db.execute(
            select(Match).where(
                ((Match.user_id == user.id) | (Match.matched_user_id == user.id))
                & (Match.lifecycle == "active")
            )
        )
    ).scalars().all()

    now = mss.utc_now()
    items: List[schemas.MatchListItem] = []

    for match in matches:
        peer_id = match.matched_user_id if match.user_id == user.id else match.user_id
        peer = (await db.execute(select(User).where(User.id == peer_id))).scalar_one_or_none()

        # Latest pending proposal (if any)
        active_proposal = (
            await db.execute(
                select(VideoCallProposal)
                .where(
                    VideoCallProposal.match_id == match.id,
                    VideoCallProposal.status == "pending",
                )
                .order_by(VideoCallProposal.id.desc())
            )
        ).scalars().first()

        # Current scheduled call (scheduled | in_progress), latest first
        call = (
            await db.execute(
                select(ScheduledCall)
                .where(
                    ScheduledCall.match_id == match.id,
                    ScheduledCall.status.in_(("scheduled", "in_progress")),
                )
                .order_by(ScheduledCall.id.desc())
            )
        ).scalars().first()

        scheduled_call_resp = None
        scheduled_start = None
        if call is not None:
            scheduled_start = call.scheduled_start_utc
            user1 = (await db.execute(select(User).where(User.id == call.user1_id))).scalar_one_or_none()
            user2 = (await db.execute(select(User).where(User.id == call.user2_id))).scalar_one_or_none()
            scheduled_call_resp = _build_scheduled_call_response(call, user, user1, user2)

        # hours_left for the card copy
        hours_left = None
        if match.text_state == "open" and match.created_at is not None:
            created = match.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            hours_left = max(0, int((created + timedelta(hours=mss.TEXT_WINDOW_HOURS) - now).total_seconds() // 3600))
        elif match.expires_at is not None:
            exp = match.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            hours_left = max(0, int((exp - now).total_seconds() // 3600))

        is_proposer = active_proposal is not None and active_proposal.proposer_user_id == user.id

        card_display = mss.compute_match_card_display(
            match.text_state, match.call_status, match.lifecycle,
            hours_left=hours_left, scheduled_start=scheduled_start, is_proposer=is_proposer,
        )
        # Spec §Transition rules: name the peer in the proposer-waiting card. The
        # pure fn lacks the name, so substitute here.
        if is_proposer and match.call_status == "proposal_pending":
            card_display = f"Waiting for {(peer.name if peer else None) or 'them'} to confirm"

        is_a = mss._is_user_a(match, user.id)
        self_response = match.exit_survey_user_a_response if is_a else match.exit_survey_user_b_response
        peer_response = match.exit_survey_user_b_response if is_a else match.exit_survey_user_a_response

        items.append(schemas.MatchListItem(
            match_id=match.id,
            peer_user=schemas.PeerUserSummary(
                id=peer.id if peer else peer_id,
                name=peer.name if peer else None,
                timezone=peer.timezone if peer else None,
                no_show_count=(peer.no_show_count or 0) if peer else 0,
            ),
            text_state=match.text_state,
            call_status=match.call_status,
            lifecycle=match.lifecycle,
            text_locked_at=match.text_locked_at,
            expires_at=match.expires_at,
            card_display=card_display,
            active_proposal=(
                schemas.VideoCallProposalResponse.model_validate(active_proposal)
                if active_proposal is not None else None
            ),
            scheduled_call=scheduled_call_resp,
            exit_survey_self_response=self_response,
            exit_survey_peer_response=peer_response,
            contact_reveal_unlocked=bool(match.contact_reveal_unlocked),
        ))

    return items


@router.get("/me/upcoming-calls", response_model=List[schemas.ScheduledCallResponse])
async def get_my_upcoming_calls(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Scheduling V2 — the viewer's upcoming (future, status='scheduled') calls,
    earliest first. Spec: DatingAppProj/SCHEDULING_V2.md §Endpoints (me/upcoming-calls)."""
    now = mss.utc_now()
    calls = (
        await db.execute(
            select(ScheduledCall)
            .where(
                ((ScheduledCall.user1_id == user.id) | (ScheduledCall.user2_id == user.id))
                & (ScheduledCall.status == "scheduled")
                & (ScheduledCall.scheduled_start_utc > now)
            )
            .order_by(ScheduledCall.scheduled_start_utc.asc())
        )
    ).scalars().all()

    out: List[schemas.ScheduledCallResponse] = []
    for call in calls:
        user1 = (await db.execute(select(User).where(User.id == call.user1_id))).scalar_one_or_none()
        user2 = (await db.execute(select(User).where(User.id == call.user2_id))).scalar_one_or_none()
        out.append(_build_scheduled_call_response(call, user, user1, user2))
    return out

# ============================================================================
# SCHEDULING V2 — PROPOSAL LIFECYCLE (propose / accept / counter)
# Spec: DatingAppProj/SCHEDULING_V2.md §Endpoints + §User Flows (Flow 1,3,6)
# ============================================================================


def _is_participant(match: Match, user_id: int) -> bool:
    return match.user_id == user_id or match.matched_user_id == user_id


def _parse_start_utc(raw: datetime) -> datetime:
    """Normalize an incoming start time to tz-aware UTC and validate the window.

    Raises HTTPException(400) if the time is in the past or beyond the 72h
    proposal window. Pydantic already parsed the ISO string into a datetime.
    """
    start = raw
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    now = mss.utc_now()
    if start <= now:
        raise HTTPException(status_code=400, detail="proposed_start_utc must be in the future")
    if start > now + timedelta(hours=mss.PROPOSAL_WINDOW_HOURS):
        raise HTTPException(
            status_code=400,
            detail=f"proposed_start_utc must be within {mss.PROPOSAL_WINDOW_HOURS}h",
        )
    return start


async def _notify_peer_best_effort(
    db: AsyncSession, peer_user_id: int, sender: User, kind: str, match_id: int,
    when: str = "",
):
    """Best-effort proposal-lifecycle push to the peer. Can NEVER raise.

    Wires the V2 typed senders (Task 7.1). `sender` is the actor; `peer` is the
    recipient. `when` is a pre-formatted human time string for the date.
    """
    try:
        peer = (await db.execute(select(User).where(User.id == peer_user_id))).scalar_one_or_none()
        if peer is None:
            return
        peer_name = sender.name or "Your match"
        if kind == "proposal":
            await push.notify_proposal_received(
                recipient=peer, peer_name=peer_name, match_id=match_id, when=when)
        elif kind == "accepted":
            await push.notify_proposal_accepted(
                recipient=peer, peer_name=peer_name, match_id=match_id, when=when)
        elif kind == "counter":
            await push.notify_counter_proposal_received(
                recipient=peer, peer_name=peer_name, match_id=match_id, when=when)
    except Exception as exc:  # pragma: no cover - best-effort, never break the endpoint
        logger.warning(f"[PUSH] best-effort {kind} notify failed: {exc}")


@router.post("/calls/propose", response_model=VideoCallProposalResponse)
async def propose_call(
    body: ProposeCallRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Flow 1 — a participant proposes a single video-date time (30 min slot).

    Only one 'pending' proposal may exist per match (enforced by a partial unique
    index). If one already exists, returns 409 with the active proposal so the
    client can flip to a review UI (Flow 6).
    """
    start = _parse_start_utc(body.proposed_start_utc)
    end = start + timedelta(minutes=mss.DATE_DURATION_MIN)

    try:
        m = await mss._lock_match(db, body.match_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Match not found")

    if not _is_participant(m, user.id):
        raise HTTPException(status_code=403, detail="You are not a participant in this match")

    if m.lifecycle != "active" or m.text_state == "archived":
        raise HTTPException(status_code=409, detail="This match is not schedulable")

    existing = (
        await db.execute(
            select(VideoCallProposal).where(
                VideoCallProposal.match_id == m.id,
                VideoCallProposal.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A proposal is already pending",
                "active_proposal": VideoCallProposalResponse.model_validate(existing).model_dump(mode="json"),
            },
        )

    proposal = VideoCallProposal(
        match_id=m.id,
        proposer_user_id=user.id,
        proposed_start_utc=start,
        proposed_end_utc=end,
        status="pending",
    )
    db.add(proposal)

    if mss.is_legal_call_status(m.call_status, "proposal_pending"):
        m.call_status = "proposal_pending"

    # System message (only when text is OPEN — spec Flow 2 step 5: no in-chat
    # system message when text is locked). Added to this session before commit.
    if m.text_state == "open":
        peer_id_for_msg = m.matched_user_id if m.user_id == user.id else m.user_id
        peer = (await db.execute(select(User).where(User.id == peer_id_for_msg))).scalar_one_or_none()
        proposer_name = user.name or "Your match"
        peer_name = (peer.name if peer else None) or "your match"
        when = start.strftime("%a %-I %p")
        await mss.write_system_message(
            db, m, "proposal_created",
            f"{proposer_name} proposed a video date for {when}. {peer_name}, review the proposal.",
        )

    await db.commit()
    await db.refresh(proposal)

    peer_id = m.matched_user_id if m.user_id == user.id else m.user_id
    await _notify_peer_best_effort(
        db, peer_id, user, "proposal", m.id, when=start.strftime("%a %-I %p"))

    return proposal


def _build_scheduled_call_response(call: ScheduledCall, viewer: User,
                                   user1: User, user2: User) -> ScheduledCallResponse:
    """Construct a ScheduledCallResponse for a ScheduledCall (V2 accept flow)."""
    if call.user1_id == viewer.id:
        other = user2
        other_user_name = user2.name if user2 else "Unknown User"
        other_user_id = call.user2_id
    else:
        other = user1
        other_user_name = user1.name if user1 else "Unknown User"
        other_user_id = call.user1_id

    start_time_str = call.scheduled_start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_time_str = call.scheduled_end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    return ScheduledCallResponse(
        id=call.id,
        user_id=viewer.id,
        match_id=call.match_id,
        user1_id=call.user1_id,
        user2_id=call.user2_id,
        user1_name=user1.name if user1 else None,
        user2_name=user2.name if user2 else None,
        other_user_name=other_user_name,
        other_user_id=other_user_id,
        other_user_firebase_uid=other.firebase_uid if other else None,
        start_time_utc=start_time_str,
        end_time_utc=end_time_str,
        scheduled_start_utc=call.scheduled_start_utc,
        scheduled_end_utc=call.scheduled_end_utc,
        duration_minutes=call.duration_minutes,
        status=call.status,
        user1_confirmed=call.user1_confirmed,
        user2_confirmed=call.user2_confirmed,
        user1_confirmed_at=call.user1_confirmed_at,
        user2_confirmed_at=call.user2_confirmed_at,
        call_room_id=call.call_room_id,
        call_started_at=call.call_started_at,
        call_ended_at=call.call_ended_at,
        actual_duration_minutes=call.actual_duration_minutes,
        original_call_id=call.original_call_id,
        reschedule_count=call.reschedule_count,
        user1_notified=call.user1_notified,
        user2_notified=call.user2_notified,
        reminder_sent=call.reminder_sent,
        created_at=call.created_at,
        updated_at=call.updated_at,
    )


@router.post("/calls/{proposal_id}/accept", response_model=ScheduledCallResponse)
async def accept_proposal(
    proposal_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Flow 3 — the NON-proposer accepts a pending proposal, creating a
    ScheduledCall (30 min) and flipping the match to call_status='scheduled'."""
    proposal = (
        await db.execute(
            select(VideoCallProposal)
            .where(VideoCallProposal.id == proposal_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail=f"Proposal is already {proposal.status}")

    m = await mss._lock_match(db, proposal.match_id)
    if not _is_participant(m, user.id):
        raise HTTPException(status_code=403, detail="You are not a participant in this match")
    if user.id == proposal.proposer_user_id:
        raise HTTPException(status_code=403, detail="You cannot accept your own proposal")

    now = mss.utc_now()
    proposal.status = "accepted"
    proposal.responded_at = now

    call = ScheduledCall(
        match_id=m.id,
        user1_id=m.user_id,
        user2_id=m.matched_user_id,
        scheduled_start_utc=proposal.proposed_start_utc,
        scheduled_end_utc=proposal.proposed_end_utc,
        duration_minutes=mss.DATE_DURATION_MIN,
        status="scheduled",
    )
    db.add(call)

    m.call_status = "scheduled"

    user1 = (await db.execute(select(User).where(User.id == m.user_id))).scalar_one_or_none()
    user2 = (await db.execute(select(User).where(User.id == m.matched_user_id))).scalar_one_or_none()
    if user1 is not None:
        user1.total_calls_scheduled = (user1.total_calls_scheduled or 0) + 1
    if user2 is not None:
        user2.total_calls_scheduled = (user2.total_calls_scheduled or 0) + 1

    when = call.scheduled_start_utc.strftime("%a %-I %p")
    await mss.write_system_message(
        db, m, "call_scheduled", f"Video date scheduled for {when}.",
    )

    await db.commit()
    await db.refresh(call)
    await db.refresh(user1)
    await db.refresh(user2)

    await _notify_peer_best_effort(
        db, proposal.proposer_user_id, user, "accepted", m.id,
        when=call.scheduled_start_utc.strftime("%a %-I %p"))

    return _build_scheduled_call_response(call, user, user1, user2)


@router.post("/calls/{proposal_id}/counter", response_model=VideoCallProposalResponse)
async def counter_proposal(
    proposal_id: int,
    body: CounterProposalRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Flow 6 — the NON-proposer counters the active proposal with a new time:
    supersede the old pending proposal and insert a new pending one."""
    start = _parse_start_utc(body.proposed_start_utc)
    end = start + timedelta(minutes=mss.DATE_DURATION_MIN)

    proposal = (
        await db.execute(
            select(VideoCallProposal)
            .where(VideoCallProposal.id == proposal_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail=f"Proposal is already {proposal.status}")

    m = await mss._lock_match(db, proposal.match_id)
    if not _is_participant(m, user.id):
        raise HTTPException(status_code=403, detail="You are not a participant in this match")
    if user.id == proposal.proposer_user_id:
        raise HTTPException(status_code=403, detail="Only the recipient can counter this proposal")

    now = mss.utc_now()
    # Supersede the old pending row and FLUSH before inserting the new pending
    # row, otherwise the partial unique index (one 'pending' per match) rejects
    # two pending rows existing simultaneously in the same transaction.
    proposal.status = "superseded"
    proposal.responded_at = now
    await db.flush()

    new_proposal = VideoCallProposal(
        match_id=m.id,
        proposer_user_id=user.id,
        proposed_start_utc=start,
        proposed_end_utc=end,
        status="pending",
    )
    db.add(new_proposal)

    if mss.is_legal_call_status(m.call_status, "proposal_pending"):
        m.call_status = "proposal_pending"

    counter_name = user.name or "Your match"
    when = start.strftime("%a %-I %p")
    await mss.write_system_message(
        db, m, "proposal_countered",
        f"{counter_name} suggested a new video date time: {when}.",
    )

    await db.commit()
    await db.refresh(new_proposal)

    await _notify_peer_best_effort(
        db, proposal.proposer_user_id, user, "counter", m.id,
        when=start.strftime("%a %-I %p"))

    return new_proposal


@router.post("/calls/{call_id}/cancel", response_model=ScheduledCallResponse)
async def cancel_call(
    call_id: int,
    reason: str = "User cancelled",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel a scheduled call (can be used for rejections)"""
    result = await db.execute(
        select(ScheduledCall)
        .where(ScheduledCall.id == call_id)
        .options(selectinload(ScheduledCall.user1), selectinload(ScheduledCall.user2))
    )
    call = result.scalars().first()
    
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    
    # Check if user is part of this call
    if call.user1_id != user.id and call.user2_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to cancel this call")
    
    # Check if call can be cancelled
    if call.status not in ['scheduled', 'in_progress']:
        raise HTTPException(status_code=400, detail="Call cannot be cancelled in its current status")
    
    # Update call status
    call.status = 'cancelled'
    call.call_ended_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(call)
    
    logger.info(f"Call {call_id} cancelled by user {user.id} with reason: {reason}")
    return call


# ---------------------------------------------------------------------------
# Task 4.6 — No-show detection endpoint (cron-facing, but a real endpoint)
# ---------------------------------------------------------------------------

NO_SHOW_GRACE_MIN = 10


@router.post("/calls/{call_id}/no-show", response_model=dict)
async def mark_call_no_show(
    call_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a scheduled call as no-show. Logs one NoShowEvent per non-joiner,
    bumps users.no_show_count, and applies the 2-strikes-same-match termination.

    Authorization: the caller MUST be a participant of the call's match. The set
    of no-showers is derived ONLY from the authoritative join flags
    (user1_joined / user2_joined) — there is no caller-supplied override, so a
    participant cannot frame the other party or stamp a no-show on a stranger.
    """
    result = await db.execute(select(ScheduledCall).where(ScheduledCall.id == call_id))
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=404, detail="Scheduled call not found")

    # Participant check — only the two users on this call's match may act on it.
    if user.id not in (call.user1_id, call.user2_id):
        raise HTTPException(status_code=403, detail="Not a participant of this call")

    grace_deadline = call.scheduled_start_utc + timedelta(minutes=NO_SHOW_GRACE_MIN)
    if mss.utc_now() < grace_deadline:
        raise HTTPException(status_code=409, detail="grace_period_not_elapsed")

    if call.status != "scheduled":
        raise HTTPException(status_code=409, detail=f"call already {call.status}")

    # Non-joiners derived solely from the authoritative join flags.
    non_joiner_ids = [
        uid
        for uid, joined in (
            (call.user1_id, call.user1_joined),
            (call.user2_id, call.user2_joined),
        )
        if not joined
    ]

    # Both participants joined -> no no-show occurred; do not fabricate one.
    if not non_joiner_ids:
        return {"no_show_count": 0, "match_terminated": False}

    res = await mss.record_no_show(db, call, non_joiner_ids)
    await db.commit()

    # Best-effort push: date_no_show_reschedule if not terminated,
    # match_terminated_no_show if terminated. Sent to both participants.
    try:
        u1 = (await db.execute(select(User).where(User.id == call.user1_id))).scalar_one_or_none()
        u2 = (await db.execute(select(User).where(User.id == call.user2_id))).scalar_one_or_none()
        terminated = res["match_terminated"]
        for recipient, peer in ((u1, u2), (u2, u1)):
            if recipient is None:
                continue
            peer_name = (peer.name if peer else None) or "your match"
            if terminated:
                await push.notify_match_terminated_no_show(
                    recipient=recipient, peer_name=peer_name, match_id=call.match_id)
            else:
                await push.notify_date_no_show_reschedule(
                    recipient=recipient, peer_name=peer_name, match_id=call.match_id)
    except Exception:
        logger.exception("no-show push notification failed (non-fatal)")

    logger.info(
        f"call {call_id}: no_show logged={res['no_show_count_logged']} "
        f"terminated={res['match_terminated']}"
    )
    return {
        "no_show_count": res["no_show_count_logged"],
        "match_terminated": res["match_terminated"],
    }