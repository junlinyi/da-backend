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
from app.services import push_notification_service as push

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


async def _notify_exit_survey(db: AsyncSession, m: Match, responder_id: int, response: bool) -> None:
    """Best-effort exit-survey pushes based on the post-write survey state.

    - both yes  -> text_unlocked_mutual_yes to both
    - one yes, other not responded -> partner_responded_yes to the non-responder
    - any no    -> match_terminated_survey_no to both (asymmetric)
    """
    a_id, b_id = m.user_id, m.matched_user_id
    user_a = (await db.execute(select(User).where(User.id == a_id))).scalar_one_or_none()
    user_b = (await db.execute(select(User).where(User.id == b_id))).scalar_one_or_none()
    if user_a is None or user_b is None:
        return
    a_resp = m.exit_survey_user_a_response  # user_a == m.user_id
    b_resp = m.exit_survey_user_b_response

    def name_of(u) -> str:
        return (u.name if u else None) or "your match"

    if a_resp is False or b_resp is False:
        # Either user said no -> terminated. Asymmetric copy by who just responded "no".
        for recipient, peer in ((user_a, user_b), (user_b, user_a)):
            is_no_er = (recipient.id == responder_id and response is False)
            await push.notify_match_terminated_survey_no(
                recipient=recipient, peer_name=name_of(peer),
                match_id=m.id, is_no_er=is_no_er)
    elif a_resp is True and b_resp is True:
        # Both yes -> mutual unlock, notify both.
        for recipient, peer in ((user_a, user_b), (user_b, user_a)):
            await push.notify_text_unlocked_mutual_yes(
                recipient=recipient, peer_name=name_of(peer), match_id=m.id)
    else:
        # Exactly one "yes" recorded so far -> nudge the non-responder.
        if a_resp is True and b_resp is None:
            await push.notify_partner_responded_yes(
                recipient=user_b, peer_name=name_of(user_a), match_id=m.id)
        elif b_resp is True and a_resp is None:
            await push.notify_partner_responded_yes(
                recipient=user_a, peer_name=name_of(user_b), match_id=m.id)


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

    # Best-effort push: both-yes -> text_unlocked_mutual_yes (both),
    # one-yes-other-none -> partner_responded_yes (non-responder),
    # any-no -> match_terminated_survey_no (both, asymmetric copy).
    try:
        await _notify_exit_survey(db, m, responder_id=user.id, response=body.response)
    except Exception:
        logger.exception("exit-survey push notification failed (non-fatal)")

    return schemas.ExitSurveyResultResponse(
        match_lifecycle=m.lifecycle,
        call_status=m.call_status,
        text_state=m.text_state,
        contact_reveal_unlocked=m.contact_reveal_unlocked,
    )


@router.post("/{match_id}/unmatch", response_model=schemas.UnmatchResultResponse)
async def unmatch(
    match_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User-initiated unmatch: terminate the match and close the conversation.

    Distinct from block (users.py block_user, which stays): this is the polite
    "remove this match" action surfaced in the chat header and profile card.
    The caller must be a participant; idempotent if already terminated. Sets
    lifecycle='terminated' + text_state='archived', deactivates the Postgres
    conversation, and archives the Firestore conversation doc so iOS stops
    showing it. A terminated match is excluded from Discover for both users.
    """
    await _load_participant_match(db, match_id, user.id)
    try:
        m = await mss.unmatch(db, match_id)
    except ValueError as e:
        if str(e) == "match_not_found":
            raise HTTPException(status_code=404, detail="Match not found")
        raise
    await db.commit()

    # Archive the Firestore conversation so iOS stops showing it (mirrors
    # block_user's SAFE-03 archive). Best-effort: the Postgres state is already
    # committed and authoritative.
    peer_id = m.matched_user_id if mss._is_user_a(m, user.id) else m.user_id
    peer = (await db.execute(select(User).where(User.id == peer_id))).scalar_one_or_none()
    if peer is not None and user.firebase_uid and peer.firebase_uid:
        try:
            from firebase_admin import firestore as fs_admin
            fs_db = fs_admin.client()
            sorted_uids = "_".join(sorted([user.firebase_uid, peer.firebase_uid]))
            fs_db.collection("conversations").document(sorted_uids).set(
                {"archived": True, "active": False}, merge=True)
        except Exception:
            logger.warning("Failed to archive Firestore conversation on unmatch", exc_info=True)

    return schemas.UnmatchResultResponse(
        match_lifecycle=m.lifecycle,
        call_status=m.call_status,
        text_state=m.text_state,
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
