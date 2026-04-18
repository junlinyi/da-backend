# app/routers/reporting.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models import User, Report
from app.schemas import ReportCreate, ReportResponse
from app.dependencies import get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=ReportResponse, status_code=201)
async def submit_report(
    report_data: ReportCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Submit a report against another user. Any authenticated (non-banned) user can file a report.
    Reports are stored in PostgreSQL and reviewed by admins via the admin panel.
    """
    if report_data.reported_firebase_uid == current_user.firebase_uid:
        raise HTTPException(status_code=400, detail="Cannot report yourself")

    # Resolve reported user by Firebase UID
    result = await db.execute(
        select(User).where(User.firebase_uid == report_data.reported_firebase_uid)
    )
    reported_user = result.scalars().first()
    if not reported_user:
        raise HTTPException(status_code=404, detail="Reported user not found")

    report = Report(
        reporter_id=current_user.id,
        reported_user_id=reported_user.id,
        reason=report_data.reason,
        details=report_data.details,
        status="pending"
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    logger.info(f"[REPORT] User {current_user.id} reported user {reported_user.id} for: {report_data.reason}")
    return report
