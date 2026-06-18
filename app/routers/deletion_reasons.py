# app/routers/deletion_reasons.py

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import DeletionReason
from app.schemas import DeletionReasonCreate, DeletionReasonKind
from app.dependencies import verify_firebase_token
from app.limiter import limiter
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/deletion-reasons", status_code=204)
@limiter.limit("1/minute")
async def record_deletion_reason(
    request: Request,
    payload: DeletionReasonCreate,
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
):
    """Record an anonymous churn reason just before account deletion.

    Auth'd (so only real users can write) but the user id is intentionally NOT
    persisted — the row carries no identifier, keeping it GDPR retention-free.
    See ACCOUNT_DELETION_IOS_SPEC.md DD-5. `free_text` is kept only for the
    'other' reason; the Pydantic validator + DB CHECK both enforce that.
    """
    free_text = payload.free_text if payload.reason == DeletionReasonKind.other else None
    db.add(DeletionReason(reason=payload.reason.value, free_text=free_text))
    await db.commit()
    return Response(status_code=204)
