# app/routers/matches.py
"""Match-scoped endpoints for Scheduling V2 (Task 4.7):
exit-survey, contact (reveal-gated), and reveal-contact analytics stamp.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.database import get_db
from app.dependencies import get_current_user
from app.models import Match, User
from app.services import match_state_service as mss

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/matches", tags=["matches"])


async def _load_participant_match(db: AsyncSession, match_id: int, user_id: int) -> Match:
    """Load the match and enforce that the caller is a participant.

    404 if the match doesn't exist, 403 if the caller is not a participant.
    """
    m = (await db.execute(select(Match).where(Match.id == match_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Match not found")
    if user_id not in (m.user_id, m.matched_user_id):
        raise HTTPException(status_code=403, detail="Not a match participant")
    return m


@router.post("/{match_id}/exit-survey", response_model=schemas.ExitSurveyResultResponse)
async def submit_exit_survey(
    match_id: int,
    body: schemas.ExitSurveyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a yes/no response to the post-call exit survey."""
    await _load_participant_match(db, match_id, user.id)
    try:
        m = await mss.process_exit_survey(db, match_id, user.id, body.response)
    except ValueError as e:
        msg = str(e)
        if msg == "not_pending_survey":
            raise HTTPException(status_code=400, detail="Survey is not pending")
        if msg == "already_responded":
            raise HTTPException(status_code=409, detail="Already responded")
        if msg == "match_not_found":
            raise HTTPException(status_code=404, detail="Match not found")
        raise
    await db.commit()

    # Best-effort push (TODO Task 7.1): both-yes -> text_unlocked_mutual_yes,
    # one-yes-other-none -> partner_responded_yes, any-no -> match_terminated_survey_no.
    try:
        pass  # TODO(7.1): wire exit-survey push notifications.
    except Exception:
        logger.exception("exit-survey push notification failed (non-fatal)")

    return schemas.ExitSurveyResultResponse(
        match_lifecycle=m.lifecycle,
        call_status=m.call_status,
        text_state=m.text_state,
        contact_reveal_unlocked=m.contact_reveal_unlocked,
    )


@router.get("/{match_id}/contact", response_model=schemas.ContactResponse)
async def get_contact(
    match_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the partner's contact info (gated on contact_reveal_unlocked)."""
    m = await _load_participant_match(db, match_id, user.id)
    if not m.contact_reveal_unlocked:
        raise HTTPException(status_code=403, detail="Contact not yet unlocked")

    peer_id = m.matched_user_id if mss._is_user_a(m, user.id) else m.user_id
    peer = (await db.execute(select(User).where(User.id == peer_id))).scalar_one_or_none()
    if peer is None:
        raise HTTPException(status_code=404, detail="Peer not found")

    return schemas.ContactResponse(
        peer_phone_number=peer.phone_number,
        peer_phone_country_code=peer.phone_country_code,
    )


@router.post("/{match_id}/reveal-contact", response_model=dict)
async def reveal_contact(
    match_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stamp that this user has revealed/viewed their partner's contact (analytics)."""
    m = await _load_participant_match(db, match_id, user.id)
    if not m.contact_reveal_unlocked:
        raise HTTPException(status_code=403, detail="Contact not yet unlocked")

    now = mss.utc_now()
    if mss._is_user_a(m, user.id):
        m.contact_revealed_to_user_a_at = now
    else:
        m.contact_revealed_to_user_b_at = now
    await db.commit()

    return {"revealed_at": now.isoformat()}
