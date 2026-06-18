# app/routers/birthdate_change_requests.py
"""User-facing birthdate-correction request endpoints (AGE_VERIFICATION_SPEC.md F4).

Birthdate is immutable post-signup; the only way a user can change theirs is to
submit a correction request, which an admin reviews (see admin.py for F5).
Mounted under the /users prefix → /users/me/birthdate-change-requests.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import logging

from app.database import get_db
from app.models import BirthdateChangeRequest, User
from app.schemas import BirthdateChangeRequestCreate, BirthdateChangeRequestResponse
from app.dependencies import get_current_user
from app.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/me/birthdate-change-requests", response_model=BirthdateChangeRequestResponse)
@limiter.limit("5/day")
async def create_birthdate_change_request(
    request: Request,
    body: BirthdateChangeRequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a request to correct your birthday. 18+ is enforced at the schema
    layer and the DB CHECK constraint. At most one pending request per user."""
    if current_user.birthdate is None:
        # No birthdate to correct yet — they should set it via onboarding first.
        raise HTTPException(
            status_code=400,
            detail="You haven't set a birthday yet. Finish your profile first.",
        )

    if body.proposed_birthdate == current_user.birthdate:
        raise HTTPException(
            status_code=400,
            detail="That's already your birthday — no change needed.",
        )

    # One open request per user keeps the admin queue clean and blocks spam.
    existing = await db.execute(
        select(BirthdateChangeRequest.id).where(
            BirthdateChangeRequest.user_id == current_user.id,
            BirthdateChangeRequest.status == "pending",
        ).limit(1)
    )
    if existing.scalars().first() is not None:
        raise HTTPException(
            status_code=409,
            detail="You already have a pending birthday-correction request.",
        )

    change_request = BirthdateChangeRequest(
        user_id=current_user.id,
        current_birthdate=current_user.birthdate,
        proposed_birthdate=body.proposed_birthdate,
        reason=body.reason,
        status="pending",
    )
    db.add(change_request)
    await db.commit()
    await db.refresh(change_request)
    logger.info(f"[BIRTHDATE] User {current_user.id} submitted correction request {change_request.id}")
    return change_request


@router.get("/me/birthdate-change-requests", response_model=list[BirthdateChangeRequestResponse])
async def list_my_birthdate_change_requests(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the caller's own correction requests (any status), newest first."""
    result = await db.execute(
        select(BirthdateChangeRequest)
        .where(BirthdateChangeRequest.user_id == current_user.id)
        .order_by(BirthdateChangeRequest.submitted_at.desc())
    )
    return result.scalars().all()
