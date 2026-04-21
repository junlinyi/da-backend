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
    SchedulingProposal, ProposalTimeSlot,
    ProposalResponse, CounterProposalTimeSlot, MatchOutcome
)
from app.schemas import (
    UserSchedulingPreferenceCreate, UserSchedulingPreferenceResponse,
    ScheduledCallCreate, ScheduledCallResponse,
    # Proposal system schemas
    SchedulingProposalCreate, SchedulingProposalResponse, ProposalResponseCreate,
    ProposalResponseResponse, ProposalListResponse, ScheduledCallFromProposal,
    ProposalStatus, ProposalResponseType
)
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
        else:
            other_user_name = user1.name if user1 else "Unknown User"
            other_user_id = call.user1_id
        
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

@router.get("/me/matches", response_model=List[dict])
async def get_my_matches_without_calls(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's unscheduled matches within the 48-hour scheduling window.

    Returns only matches where:
    - No scheduled call exists yet
    - No pending proposal exists yet (those appear in /proposals)
    - Match was created within the last 48 hours (Tier 2 window)

    Each result includes `initiator_id` (the user who swiped / User A).
    """
    from datetime import datetime, timezone, timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)

    # Matches within the 48h window, excluding expired/blocked
    matches_query = select(Match).where(
        ((Match.user_id == user.id) | (Match.matched_user_id == user.id))
        & (Match.created_at >= cutoff)
        & (~Match.status.in_(["expired", "blocked", "rejected"]))
    )
    matches_result = await db.execute(matches_query)
    matches = matches_result.scalars().all()

    # Match IDs that already have scheduled calls (any status)
    calls_query = select(ScheduledCall.match_id).where(
        (ScheduledCall.user1_id == user.id) | (ScheduledCall.user2_id == user.id)
    )
    calls_result = await db.execute(calls_query)
    scheduled_match_ids = {row[0] for row in calls_result.fetchall()}

    # Match IDs that already have a pending proposal
    from app.models import SchedulingProposal as ProposalModel
    proposals_query = select(ProposalModel.match_id).where(
        ((ProposalModel.proposer_id == user.id) | (ProposalModel.receiver_id == user.id))
        & (ProposalModel.status == "pending")
    )
    proposals_result = await db.execute(proposals_query)
    proposed_match_ids = {row[0] for row in proposals_result.fetchall()}

    exclude_ids = scheduled_match_ids | proposed_match_ids

    unscheduled_matches = []
    for match in matches:
        if match.id in exclude_ids:
            continue

        if match.user_id == user.id:
            other_user_id = match.matched_user_id
        else:
            other_user_id = match.user_id

        other_user_query = await db.execute(select(User).where(User.id == other_user_id))
        other_user = other_user_query.scalar_one_or_none()

        # Deadline for scheduling (48h from match creation)
        deadline = None
        if match.created_at:
            dt = match.created_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            deadline = (dt + timedelta(hours=48)).isoformat()

        unscheduled_matches.append({
            "id": match.id,
            "user1_id": match.user_id,           # initiator (swiped right)
            "user2_id": match.matched_user_id,   # recipient
            "initiator_id": match.user_id,        # explicit field: User A
            "other_user_id": other_user_id,
            "other_user_name": other_user.name if other_user else "Unknown User",
            "created_at": match.created_at.isoformat() if match.created_at else None,
            "scheduling_deadline": deadline,
        })

    return unscheduled_matches

@router.post("/calls", response_model=ScheduledCallResponse)
async def schedule_call(
    call_data: ScheduledCallCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    logger.info(f"[API] schedule_call called by user {user.id} (firebase_uid={user.firebase_uid}) with data: {call_data}")
    try:
        # Verify user is a participant
        if user.id not in [call_data.user1_id, call_data.user2_id]:
            logger.warning(f"User {user.id} not a participant in call: {call_data.user1_id}, {call_data.user2_id}")
            raise HTTPException(status_code=403, detail="You can only schedule calls you're participating in")
        # Calculate end time from start time and duration
        scheduled_end_utc = call_data.scheduled_start_utc + timedelta(minutes=call_data.duration_minutes)
        logger.info(f"Checking conflicts for user1_id={call_data.user1_id}, user2_id={call_data.user2_id}, start={call_data.scheduled_start_utc}, end={scheduled_end_utc}")
        # Conflict check: only block if there's an OVERLAPPING ACTIVE call.
        # Availability-grid logic was removed with the two-tier migration; the app now
        # relies on user intent (they're signaling availability by tapping Call Now /
        # Propose Times). We only need to prevent double-booking actually-live calls.
        overlap_sql = text("""SELECT EXISTS(
            SELECT 1 FROM scheduled_calls
            WHERE (user1_id = :user_id OR user2_id = :user_id)
              AND status IN ('scheduled', 'in_progress')
              AND (scheduled_start_utc < :end_time AND scheduled_end_utc > :start_time)
        )""")
        user1_conflict = (await db.execute(
            overlap_sql,
            {"user_id": call_data.user1_id, "start_time": call_data.scheduled_start_utc, "end_time": scheduled_end_utc}
        )).scalar()
        user2_conflict = (await db.execute(
            overlap_sql,
            {"user_id": call_data.user2_id, "start_time": call_data.scheduled_start_utc, "end_time": scheduled_end_utc}
        )).scalar()
        logger.info(f"user1_conflict={user1_conflict}, user2_conflict={user2_conflict}")
        if user1_conflict or user2_conflict:
            logger.warning(f"Scheduling conflict detected for call: {call_data}")
            raise HTTPException(status_code=409, detail="Scheduling conflict detected - one or both users are not available at this time")
        # Create the scheduled call
        new_call = ScheduledCall(
            match_id=call_data.match_id,
            user1_id=call_data.user1_id,
            user2_id=call_data.user2_id,
            scheduled_start_utc=call_data.scheduled_start_utc,
            scheduled_end_utc=scheduled_end_utc,
            duration_minutes=call_data.duration_minutes
        )
        db.add(new_call)
        await db.commit()
        await db.refresh(new_call)
        logger.info(f"Scheduled call {new_call.id} for users {call_data.user1_id} and {call_data.user2_id}")

        # Update match_outcomes funnel: stamp call_scheduled_at (best-effort)
        try:
            outcome_q = await db.execute(
                select(MatchOutcome).where(MatchOutcome.match_id == new_call.match_id)
            )
            outcome = outcome_q.scalar_one_or_none()
            if outcome and outcome.call_scheduled_at is None:
                outcome.call_scheduled_at = datetime.now(timezone.utc)
                await db.commit()
        except Exception as exc:
            logger.warning(f"Failed to update match_outcomes.call_scheduled_at: {exc}")

        # Fetch user names for response
        user1_query = await db.execute(select(User).where(User.id == new_call.user1_id))
        user1 = user1_query.scalar_one_or_none()

        user2_query = await db.execute(select(User).where(User.id == new_call.user2_id))
        user2 = user2_query.scalar_one_or_none()

        # Determine which is the "other" user
        if new_call.user1_id == user.id:
            other_user_name = user2.name if user2 else "Unknown User"
            other_user_id = new_call.user2_id
            other_user = user2
        else:
            other_user_name = user1.name if user1 else "Unknown User"
            other_user_id = new_call.user1_id
            other_user = user1

        # S1 — notify the other participant that a call was just scheduled
        try:
            await push.notify_immediate_call_request(
                recipient=other_user, caller=user, call_id=new_call.id
            )
        except Exception as exc:
            logger.warning(f"[PUSH] S1 notification failed: {exc}")

        # Format datetime for iOS
        start_time_str = new_call.scheduled_start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_time_str = new_call.scheduled_end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

        # Return ScheduledCallResponse with all required fields
        return ScheduledCallResponse(
            id=new_call.id,
            user_id=user.id,
            match_id=new_call.match_id,
            user1_id=new_call.user1_id,
            user2_id=new_call.user2_id,
            user1_name=user1.name if user1 else None,
            user2_name=user2.name if user2 else None,
            other_user_name=other_user_name,
            other_user_id=other_user_id,
            start_time_utc=start_time_str,
            end_time_utc=end_time_str,
            scheduled_start_utc=new_call.scheduled_start_utc,
            scheduled_end_utc=new_call.scheduled_end_utc,
            duration_minutes=new_call.duration_minutes,
            status=new_call.status,
            user1_confirmed=new_call.user1_confirmed,
            user2_confirmed=new_call.user2_confirmed,
            user1_confirmed_at=new_call.user1_confirmed_at,
            user2_confirmed_at=new_call.user2_confirmed_at,
            call_room_id=new_call.call_room_id,
            call_started_at=new_call.call_started_at,
            call_ended_at=new_call.call_ended_at,
            actual_duration_minutes=new_call.actual_duration_minutes,
            original_call_id=new_call.original_call_id,
            reschedule_count=new_call.reschedule_count,
            user1_notified=new_call.user1_notified,
            user2_notified=new_call.user2_notified,
            reminder_sent=new_call.reminder_sent,
            created_at=new_call.created_at,
            updated_at=new_call.updated_at
        )
    except Exception as e:
        logger.error(f"Exception in schedule_call: {e}", exc_info=True)
        raise

@router.put("/calls/{call_id}/extend", response_model=ScheduledCallResponse)
async def extend_call(
    call_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Extend a call by 5 minutes (up to 30 minutes total)"""
    result = await db.execute(
        select(ScheduledCall).where(ScheduledCall.id == call_id)
    )
    call = result.scalars().first()
    
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    
    # Verify user is a participant
    if user.id not in [call.user1_id, call.user2_id]:
        raise HTTPException(status_code=403, detail="You can only extend calls you're participating in")
    
    # Check if call is in progress
    if call.status != "in_progress":
        raise HTTPException(status_code=400, detail="Can only extend calls that are in progress")
    
    # Check if we can extend (max 30 minutes total)
    current_duration = call.actual_duration_minutes or 15
    if current_duration >= 30:
        raise HTTPException(status_code=400, detail="Call cannot be extended beyond 30 minutes")
    
    # Extend by 5 minutes
    call.actual_duration_minutes = min(current_duration + 5, 30)
    
    await db.commit()
    await db.refresh(call)
    
    logger.info(f"Extended call {call_id} to {call.actual_duration_minutes} minutes")
    return call

@router.put("/calls/{call_id}/confirm", response_model=ScheduledCallResponse)
async def confirm_call(
    call_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Confirm a scheduled call (mark as confirmed by user)"""
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
        raise HTTPException(status_code=403, detail="Not authorized to confirm this call")
    
    # Update confirmation status
    if call.user1_id == user.id:
        call.user1_confirmed = True
        call.user1_confirmed_at = datetime.now(timezone.utc)
    else:
        call.user2_confirmed = True
        call.user2_confirmed_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(call)
    
    logger.info(f"Call {call_id} confirmed by user {user.id}")
    return call

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


# ============================================================================
# Scheduling Proposal System Endpoints
# ============================================================================

@router.post("/proposals", response_model=SchedulingProposalResponse)
async def create_scheduling_proposal(
    proposal_data: SchedulingProposalCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new scheduling proposal with 2-3 time slot options"""
    try:
        # Verify match exists and user is part of it
        match_result = await db.execute(
            select(Match).where(
                Match.id == proposal_data.match_id,
                ((Match.user_id == user.id) | (Match.matched_user_id == user.id))
            )
        )
        match = match_result.scalar_one_or_none()
        if not match:
            raise HTTPException(status_code=404, detail="Match not found or access denied")
        
        # Verify receiver is the other user in the match
        if match.user_id == user.id:
            if match.matched_user_id != proposal_data.receiver_id:
                raise HTTPException(status_code=400, detail="Invalid receiver_id for this match")
        else:
            if match.user_id != proposal_data.receiver_id:
                raise HTTPException(status_code=400, detail="Invalid receiver_id for this match")
        
        # Check for existing pending proposals
        existing_result = await db.execute(
            select(SchedulingProposal).where(
                SchedulingProposal.match_id == proposal_data.match_id,
                SchedulingProposal.status == ProposalStatus.PENDING
            )
        )
        existing_proposal = existing_result.scalar_one_or_none()
        if existing_proposal:
            raise HTTPException(status_code=400, detail="A pending proposal already exists for this match")
        
        # Create proposal with 24-hour expiration
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        proposal = SchedulingProposal(
            match_id=proposal_data.match_id,
            proposer_id=user.id,
            receiver_id=proposal_data.receiver_id,
            status=ProposalStatus.PENDING,
            message=proposal_data.message,
            expires_at=expires_at
        )
        db.add(proposal)
        await db.flush()  # Get the proposal ID
        
        # Create time slots
        for slot_data in proposal_data.time_slots:
            time_slot = ProposalTimeSlot(
                proposal_id=proposal.id,
                start_time=slot_data.start_time,
                end_time=slot_data.end_time,
                is_selected=False
            )
            db.add(time_slot)
        
        await db.commit()
        await db.refresh(proposal)
        
        # Load the proposal with relationships for response
        result = await db.execute(
            select(SchedulingProposal)
            .options(
                selectinload(SchedulingProposal.time_slots),
                selectinload(SchedulingProposal.proposer),
                selectinload(SchedulingProposal.receiver)
            )
            .where(SchedulingProposal.id == proposal.id)
        )
        proposal_with_relations = result.scalar_one()
        
        # S2 — notify the receiver that they have a new proposal to respond to
        try:
            await push.notify_proposal_received(
                recipient=proposal_with_relations.receiver,
                proposer=proposal_with_relations.proposer,
                proposal_id=proposal_with_relations.id,
            )
        except Exception as exc:
            logger.warning(f"[PUSH] S2 notification failed: {exc}")

        return SchedulingProposalResponse(
            id=proposal_with_relations.id,
            match_id=proposal_with_relations.match_id,
            proposer_id=proposal_with_relations.proposer_id,
            receiver_id=proposal_with_relations.receiver_id,
            status=proposal_with_relations.status,
            message=proposal_with_relations.message,
            created_at=proposal_with_relations.created_at,
            expires_at=proposal_with_relations.expires_at,
            responded_at=proposal_with_relations.responded_at,
            proposer_name=proposal_with_relations.proposer.name,
            receiver_name=proposal_with_relations.receiver.name,
            time_slots=[
                {
                    "id": slot.id,
                    "proposal_id": slot.proposal_id,
                    "start_time": slot.start_time,
                    "end_time": slot.end_time,
                    "is_selected": slot.is_selected,
                    "created_at": slot.created_at
                }
                for slot in proposal_with_relations.time_slots
            ]
        )

    except Exception as e:
        logger.error(f"Error creating proposal: {e}")
        await db.rollback()
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Failed to create proposal")

@router.get("/proposals", response_model=ProposalListResponse)
async def get_user_proposals(
    status: Optional[ProposalStatus] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get proposals for the current user (both sent and received)"""
    try:
        # Build query for proposals where user is proposer or receiver
        query = select(SchedulingProposal).options(
            selectinload(SchedulingProposal.time_slots),
            selectinload(SchedulingProposal.proposer),
            selectinload(SchedulingProposal.receiver)
        ).where(
            (SchedulingProposal.proposer_id == user.id) |
            (SchedulingProposal.receiver_id == user.id)
        )
        
        if status:
            query = query.where(SchedulingProposal.status == status)
        
        # Order by created_at descending
        query = query.order_by(SchedulingProposal.created_at.desc())
        
        result = await db.execute(query)
        proposals = result.scalars().all()
        
        # Count proposals by status
        pending_count = len([p for p in proposals if p.status == ProposalStatus.PENDING])
        responded_count = len([p for p in proposals if p.status != ProposalStatus.PENDING])
        
        proposal_responses = []
        for proposal in proposals:
            proposal_responses.append(SchedulingProposalResponse(
                id=proposal.id,
                match_id=proposal.match_id,
                proposer_id=proposal.proposer_id,
                receiver_id=proposal.receiver_id,
                status=proposal.status,
                message=proposal.message,
                created_at=proposal.created_at,
                expires_at=proposal.expires_at,
                responded_at=proposal.responded_at,
                proposer_name=proposal.proposer.name,
                receiver_name=proposal.receiver.name,
                time_slots=[
                    {
                        "id": slot.id,
                        "proposal_id": slot.proposal_id,
                        "start_time": slot.start_time,
                        "end_time": slot.end_time,
                        "is_selected": slot.is_selected,
                        "created_at": slot.created_at
                    }
                    for slot in proposal.time_slots
                ]
            ))
        
        return ProposalListResponse(
            proposals=proposal_responses,
            total_count=len(proposals),
            pending_count=pending_count,
            responded_count=responded_count
        )
        
    except Exception as e:
        logger.error(f"Error getting proposals: {e}")
        raise HTTPException(status_code=500, detail="Failed to get proposals")

@router.get("/proposals/{proposal_id}", response_model=SchedulingProposalResponse)
async def get_proposal(
    proposal_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific proposal by ID"""
    try:
        result = await db.execute(
            select(SchedulingProposal)
            .options(
                selectinload(SchedulingProposal.time_slots),
                selectinload(SchedulingProposal.proposer),
                selectinload(SchedulingProposal.receiver)
            )
            .where(
                SchedulingProposal.id == proposal_id,
                ((SchedulingProposal.proposer_id == user.id) | (SchedulingProposal.receiver_id == user.id))
            )
        )
        proposal = result.scalar_one_or_none()
        
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found or access denied")
        
        return SchedulingProposalResponse(
            id=proposal.id,
            match_id=proposal.match_id,
            proposer_id=proposal.proposer_id,
            receiver_id=proposal.receiver_id,
            status=proposal.status,
            message=proposal.message,
            created_at=proposal.created_at,
            expires_at=proposal.expires_at,
            responded_at=proposal.responded_at,
            proposer_name=proposal.proposer.name,
            receiver_name=proposal.receiver.name,
            time_slots=[
                {
                    "id": slot.id,
                    "proposal_id": slot.proposal_id,
                    "start_time": slot.start_time,
                    "end_time": slot.end_time,
                    "is_selected": slot.is_selected,
                    "created_at": slot.created_at
                }
                for slot in proposal.time_slots
            ]
        )
        
    except Exception as e:
        logger.error(f"Error getting proposal {proposal_id}: {e}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Failed to get proposal")

@router.post("/proposals/{proposal_id}/respond", response_model=ScheduledCallFromProposal)
async def respond_to_proposal(
    proposal_id: int,
    response_data: ProposalResponseCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Respond to a scheduling proposal (accept/reject/counter-propose)"""
    try:
        # Get the proposal
        result = await db.execute(
            select(SchedulingProposal)
            .options(
                selectinload(SchedulingProposal.time_slots),
                selectinload(SchedulingProposal.proposer),
                selectinload(SchedulingProposal.receiver)
            )
            .where(SchedulingProposal.id == proposal_id)
        )
        proposal = result.scalar_one_or_none()
        
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")
        
        # Verify user is the receiver
        if proposal.receiver_id != user.id:
            raise HTTPException(status_code=403, detail="Only the proposal receiver can respond")
        
        # Check if proposal is still pending
        if proposal.status != ProposalStatus.PENDING:
            raise HTTPException(status_code=400, detail="Proposal is no longer pending")
        
        # Check if proposal has expired
        if datetime.now(timezone.utc) > proposal.expires_at:
            proposal.status = ProposalStatus.EXPIRED
            await db.commit()
            raise HTTPException(status_code=400, detail="Proposal has expired")
        
        # Create the response
        proposal_response = ProposalResponse(
            proposal_id=proposal.id,
            response_type=response_data.response_type,
            selected_slot_id=response_data.selected_slot_id,
            counter_proposal_message=response_data.counter_proposal_message
        )
        db.add(proposal_response)
        await db.flush()  # Get the response ID
        
        # Handle different response types
        if response_data.response_type == ProposalResponseType.ACCEPT:
            # Mark the selected slot and update proposal status
            selected_slot_result = await db.execute(
                select(ProposalTimeSlot).where(ProposalTimeSlot.id == response_data.selected_slot_id)
            )
            selected_slot = selected_slot_result.scalar_one()
            selected_slot.is_selected = True

            proposal.status = ProposalStatus.ACCEPTED
            proposal.responded_at = datetime.now(timezone.utc)
            
            # Create a scheduled call
            scheduled_call = ScheduledCall(
                match_id=proposal.match_id,
                user1_id=proposal.proposer_id,
                user2_id=proposal.receiver_id,
                scheduled_start_utc=selected_slot.start_time,
                scheduled_end_utc=selected_slot.end_time,
                duration_minutes=15,  # Fixed 15-minute calls
                status="scheduled"
            )
            db.add(scheduled_call)
            await db.commit()
            await db.refresh(scheduled_call)

            # Update match_outcomes funnel: stamp call_scheduled_at (best-effort)
            try:
                outcome_q = await db.execute(
                    select(MatchOutcome).where(MatchOutcome.match_id == scheduled_call.match_id)
                )
                outcome = outcome_q.scalar_one_or_none()
                if outcome and outcome.call_scheduled_at is None:
                    outcome.call_scheduled_at = datetime.now(timezone.utc)
                    await db.commit()
            except Exception as exc:
                logger.warning(f"Failed to update match_outcomes.call_scheduled_at on proposal accept: {exc}")

            # S3 — notify the proposer that their proposal was accepted
            try:
                await push.notify_proposal_accepted(
                    proposer=proposal.proposer,
                    accepter=proposal.receiver,
                    call_id=scheduled_call.id,
                )
            except Exception as exc:
                logger.warning(f"[PUSH] S3 notification failed: {exc}")

            # Return the scheduled call with proposal details
            return ScheduledCallFromProposal(
                call=ScheduledCallResponse(
                    id=scheduled_call.id,
                    user_id=user.id,
                    match_id=scheduled_call.match_id,
                    user1_id=scheduled_call.user1_id,
                    user2_id=scheduled_call.user2_id,
                    other_user_name=proposal.proposer.name,
                    other_user_id=proposal.proposer_id,
                    start_time_utc=selected_slot.start_time.isoformat() + 'Z',
                    end_time_utc=selected_slot.end_time.isoformat() + 'Z',
                    scheduled_start_utc=scheduled_call.scheduled_start_utc,
                    scheduled_end_utc=scheduled_call.scheduled_end_utc,
                    duration_minutes=scheduled_call.duration_minutes,
                    status=scheduled_call.status,
                    user1_confirmed=scheduled_call.user1_confirmed,
                    user2_confirmed=scheduled_call.user2_confirmed,
                    user1_confirmed_at=scheduled_call.user1_confirmed_at,
                    user2_confirmed_at=scheduled_call.user2_confirmed_at,
                    call_room_id=scheduled_call.call_room_id,
                    call_started_at=scheduled_call.call_started_at,
                    call_ended_at=scheduled_call.call_ended_at,
                    actual_duration_minutes=scheduled_call.actual_duration_minutes,
                    original_call_id=scheduled_call.original_call_id,
                    reschedule_count=scheduled_call.reschedule_count,
                    user1_notified=scheduled_call.user1_notified,
                    user2_notified=scheduled_call.user2_notified,
                    reminder_sent=scheduled_call.reminder_sent,
                    created_at=scheduled_call.created_at,
                    updated_at=scheduled_call.updated_at
                ),
                proposal=SchedulingProposalResponse(
                    id=proposal.id,
                    match_id=proposal.match_id,
                    proposer_id=proposal.proposer_id,
                    receiver_id=proposal.receiver_id,
                    status=proposal.status,
                    message=proposal.message,
                    created_at=proposal.created_at,
                    expires_at=proposal.expires_at,
                    responded_at=proposal.responded_at,
                    proposer_name=proposal.proposer.name,
                    receiver_name=proposal.receiver.name,
                    time_slots=[
                        {
                            "id": slot.id,
                            "proposal_id": slot.proposal_id,
                            "start_time": slot.start_time,
                            "end_time": slot.end_time,
                            "is_selected": slot.is_selected,
                            "created_at": slot.created_at
                        }
                        for slot in proposal.time_slots
                    ]
                )
            )
            
        elif response_data.response_type == ProposalResponseType.REJECT:
            proposal.status = ProposalStatus.REJECTED
            proposal.responded_at = datetime.now(timezone.utc)
            await db.commit()

            # S4 — notify the proposer that their proposal was rejected
            try:
                await push.notify_proposal_rejected(
                    proposer=proposal.proposer, rejecter=proposal.receiver
                )
            except Exception as exc:
                logger.warning(f"[PUSH] S4 notification failed: {exc}")

        elif response_data.response_type == ProposalResponseType.COUNTER_PROPOSE:
            # Add counter proposal time slots
            if response_data.counter_time_slots:
                for counter_slot_data in response_data.counter_time_slots:
                    counter_slot = CounterProposalTimeSlot(
                        response_id=proposal_response.id,
                        start_time=counter_slot_data.start_time,
                        end_time=counter_slot_data.end_time
                    )
                    db.add(counter_slot)

            proposal.status = ProposalStatus.COUNTER_PROPOSED
            proposal.responded_at = datetime.now(timezone.utc)
            await db.commit()

            # S9 — notify the original proposer of the counter-proposal
            try:
                await push.notify_counter_proposal_received(
                    recipient=proposal.proposer,
                    proposer=proposal.receiver,
                    proposal_id=proposal.id,
                )
            except Exception as exc:
                logger.warning(f"[PUSH] S9 notification failed: {exc}")
        
        # For reject and counter-propose, return empty call but with proposal details
        return ScheduledCallFromProposal(
            call=None,
            proposal=SchedulingProposalResponse(
                id=proposal.id,
                match_id=proposal.match_id,
                proposer_id=proposal.proposer_id,
                receiver_id=proposal.receiver_id,
                status=proposal.status,
                message=proposal.message,
                created_at=proposal.created_at,
                expires_at=proposal.expires_at,
                responded_at=proposal.responded_at,
                proposer_name=proposal.proposer.name,
                receiver_name=proposal.receiver.name,
                time_slots=[
                    {
                        "id": slot.id,
                        "proposal_id": slot.proposal_id,
                        "start_time": slot.start_time,
                        "end_time": slot.end_time,
                        "is_selected": slot.is_selected,
                        "created_at": slot.created_at
                    }
                    for slot in proposal.time_slots
                ]
            ),
            message=f"Proposal {response_data.response_type.value}ed successfully"
        )
        
    except Exception as e:
        logger.error(f"Error responding to proposal {proposal_id}: {e}")
        await db.rollback()
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Failed to respond to proposal")


# ============================================================================
# TIER 1 — SPONTANEOUS CALL REQUESTS (post-match 5-minute window)
# ============================================================================

@router.post("/call-requests", response_model=dict)
async def create_call_request(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    User B (the one whose swipe triggered the match) sends a live call request
    to User A.  Expires automatically after 5 minutes.
    """
    from app.models import CallRequest, Match
    from app.schemas import CallRequestCreate
    from datetime import timedelta

    match_id = body.get("match_id")
    if not match_id:
        raise HTTPException(status_code=422, detail="match_id required")

    # Verify the match exists and the caller is a participant
    match_result = await db.execute(
        select(Match).where(
            Match.id == match_id,
            ((Match.user_id == user.id) | (Match.matched_user_id == user.id)),
        )
    )
    match = match_result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found or you are not a participant")

    # Determine recipient (the other person in the match)
    recipient_id = match.matched_user_id if match.user_id == user.id else match.user_id

    # Only allow one pending request per match at a time
    existing = await db.execute(
        select(CallRequest).where(
            CallRequest.match_id == match_id,
            CallRequest.status == "pending",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A pending call request already exists for this match")

    now = datetime.now(timezone.utc)
    call_request = CallRequest(
        match_id=match_id,
        requester_id=user.id,
        recipient_id=recipient_id,
        status="pending",
        expires_at=now + timedelta(minutes=5),
    )
    db.add(call_request)
    await db.commit()
    await db.refresh(call_request)

    logger.info(f"call_request {call_request.id}: created by user {user.id} for match {match_id}")
    return {"id": call_request.id, "expires_at": call_request.expires_at.isoformat(), "status": "pending"}


@router.get("/call-requests/incoming", response_model=list)
async def get_incoming_call_requests(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    User A polls this to find pending call requests addressed to them.
    Auto-expires stale requests at read time.
    """
    from app.models import CallRequest

    now = datetime.now(timezone.utc)

    # Auto-expire any overdue pending requests
    overdue = await db.execute(
        select(CallRequest).where(
            CallRequest.recipient_id == user.id,
            CallRequest.status == "pending",
            CallRequest.expires_at < now,
        )
    )
    for req in overdue.scalars().all():
        req.status = "expired"
    await db.commit()

    # Return remaining live pending requests
    result = await db.execute(
        select(CallRequest).where(
            CallRequest.recipient_id == user.id,
            CallRequest.status == "pending",
        )
    )
    requests = result.scalars().all()

    output = []
    for req in requests:
        requester_result = await db.execute(select(User).where(User.id == req.requester_id))
        requester = requester_result.scalar_one_or_none()
        output.append({
            "id": req.id,
            "match_id": req.match_id,
            "status": req.status,
            "expires_at": req.expires_at.isoformat(),
            "requester": {
                "id": requester.id if requester else req.requester_id,
                "name": requester.name if requester else "Unknown",
                "profile_image_url": requester.profile_image_url if requester else None,
                "firebase_uid": requester.firebase_uid if requester else "",
            },
        })
    return output


@router.get("/call-requests/{request_id}", response_model=dict)
async def get_call_request_status(
    request_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    User B polls this to check whether User A has accepted/declined.
    Also auto-expires at read time and returns room_name when accepted.
    """
    from app.models import CallRequest

    result = await db.execute(select(CallRequest).where(CallRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Call request not found")
    if req.requester_id != user.id and req.recipient_id != user.id:
        raise HTTPException(status_code=403, detail="Not your call request")

    # Auto-expire if overdue
    now = datetime.now(timezone.utc)
    if req.status == "pending" and req.expires_at < now:
        req.status = "expired"
        await db.commit()

    return {
        "id": req.id,
        "match_id": req.match_id,
        "status": req.status,
        "room_name": req.room_name,
        "expires_at": req.expires_at.isoformat(),
    }


@router.post("/call-requests/{request_id}/accept", response_model=dict)
async def accept_call_request(
    request_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User A accepts the call request. Creates a ScheduledCall and returns the Twilio room name both clients should join."""
    from app.models import CallRequest, ScheduledCall
    from datetime import timedelta

    # SELECT FOR UPDATE to prevent two concurrent accepts from both succeeding
    result = await db.execute(
        select(CallRequest).where(CallRequest.id == request_id).with_for_update()
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Call request not found")
    if req.recipient_id != user.id:
        raise HTTPException(status_code=403, detail="Only the recipient can accept")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"Request is already {req.status}")

    now = datetime.now(timezone.utc)
    if req.expires_at < now:
        req.status = "expired"
        await db.commit()
        raise HTTPException(status_code=410, detail="Call request has expired")

    room_name = f"tier1-{request_id}"
    req.status = "accepted"
    req.room_name = room_name

    # Create the ScheduledCall row so the rest of the system (no-show detection,
    # match_outcomes funnel, Upcoming Calls list) sees this Tier 1 call.
    scheduled_call = ScheduledCall(
        match_id=req.match_id,
        user1_id=req.requester_id,
        user2_id=req.recipient_id,
        scheduled_start_utc=now,
        scheduled_end_utc=now + timedelta(minutes=15),
        duration_minutes=15,
        status="in_progress",
        call_room_id=room_name,
        call_started_at=now,
    )
    db.add(scheduled_call)
    await db.commit()
    await db.refresh(scheduled_call)

    logger.info(
        f"call_request {request_id}: accepted by user {user.id}, "
        f"room={room_name}, scheduled_call={scheduled_call.id}"
    )
    return {
        "id": req.id,
        "status": "accepted",
        "room_name": room_name,
        "scheduled_call_id": scheduled_call.id,
    }


@router.post("/call-requests/{request_id}/decline", response_model=dict)
async def decline_call_request(
    request_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User A declines the call request."""
    from app.models import CallRequest

    result = await db.execute(select(CallRequest).where(CallRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Call request not found")
    if req.recipient_id != user.id:
        raise HTTPException(status_code=403, detail="Only the recipient can decline")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"Request is already {req.status}")

    req.status = "declined"
    await db.commit()

    logger.info(f"call_request {request_id}: declined by user {user.id}")
    return {"id": req.id, "status": "declined"}