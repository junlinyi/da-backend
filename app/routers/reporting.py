# app/routers/reporting.py

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_
from app.database import get_db
from app.models import User, Report
from app.schemas import ReportCreate, ReportResponse
from app.dependencies import get_current_user
from app.limiter import limiter
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=ReportResponse, status_code=201)
@limiter.limit("20/hour")
async def submit_report(
    request: Request,
    report_data: ReportCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Submit a structured report against another user. Any authenticated
    (non-banned) user can file a report. The category is a machine-readable
    enum (see schemas.ReportCategory); `details` is free text, required only
    when category == other. Reports are stored in PostgreSQL and reviewed by
    admins via the admin panel.

    Anti-abuse: rate-limited to 20/hour, plus a per-pair 24h dedupe (409) so a
    single user can't mass-flag one target (harassment-via-report).
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

    # Per-pair 24h dedupe — one open ticket per (reporter, reported) pair is
    # enough for the admin queue, and it blocks report-flooding a single target
    # regardless of context (DD/Open-Q 4: dedupe is cross-context).
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    dup = await db.execute(
        select(Report.id).where(and_(
            Report.reporter_id == current_user.id,
            Report.reported_user_id == reported_user.id,
            Report.created_at > since,
        )).limit(1)
    )
    if dup.scalars().first() is not None:
        raise HTTPException(
            status_code=409,
            detail="You've already reported this user recently."
        )

    report = Report(
        reporter_id=current_user.id,
        reported_user_id=reported_user.id,
        category=report_data.category.value,
        context=report_data.context.value,
        details=report_data.details,
        status="pending"
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    # Do NOT log `details` — it's user free text that may carry PII about the
    # reporter or the accused (Security Review §Data sensitivity).
    logger.info(
        f"[REPORT] User {current_user.id} reported user {reported_user.id} "
        f"(category={report_data.category.value}, context={report_data.context.value})"
    )
    return report
