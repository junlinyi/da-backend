# app/routers/admin.py

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models import User, Report, ScheduledCall, Match, BirthdateChangeRequest
from app.schemas import (
    ReportResponse, ReportStatusUpdate, BanRequest,
    BirthdateChangeRequestAdminItem, BirthdateChangeRequestAdminAction,
)
from app.dependencies import require_admin
from app.services.age_service import approve_birthdate_change, compute_age, BirthdateValidationError
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@router.get("/reports", response_model=list[ReportResponse])
async def list_reports(
    status: str = Query("pending", pattern="^(pending|reviewed|dismissed|all)$"),
    category: str | None = Query(None),
    context: str | None = Query(None, pattern="^(chat|video_call|profile)$"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """List reports, optionally filtered by status, category, and context. Defaults to pending only."""
    query = select(Report)
    if status != "all":
        query = query.where(Report.status == status)
    if category:
        query = query.where(Report.category == category)
    if context:
        query = query.where(Report.context == context)
    query = query.order_by(Report.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.patch("/reports/{report_id}", response_model=ReportResponse)
async def update_report_status(
    report_id: int,
    body: ReportStatusUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Mark a report as reviewed or dismissed."""
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalars().first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    report.status = body.status
    report.reviewed_at = datetime.now(timezone.utc)
    report.reviewed_by = admin.id
    await db.commit()
    await db.refresh(report)

    logger.info(f"[ADMIN] Admin {admin.id} marked report {report_id} as {body.status}")
    return report


# ---------------------------------------------------------------------------
# User banning
# ---------------------------------------------------------------------------

@router.post("/users/{user_id}/ban")
async def ban_user(
    user_id: int,
    body: BanRequest = BanRequest(),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Ban a user: sets is_active=False, blocking all API access."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot ban yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if not target.is_active:
        raise HTTPException(status_code=409, detail="User is already banned")

    target.is_active = False
    await db.commit()

    logger.info(f"[ADMIN] Admin {admin.id} banned user {user_id}. Reason: {body.reason}")
    return {"message": f"User {user_id} has been banned"}


@router.post("/users/{user_id}/unban")
async def unban_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Unban a user: sets is_active=True, restoring API access."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.is_active:
        raise HTTPException(status_code=409, detail="User is not banned")

    target.is_active = True
    await db.commit()

    logger.info(f"[ADMIN] Admin {admin.id} unbanned user {user_id}")
    return {"message": f"User {user_id} has been unbanned"}


# ---------------------------------------------------------------------------
# Report detail + action (SAFE-01)
# ---------------------------------------------------------------------------

@router.get("/reports/{report_id}")
async def get_report_detail(
    report_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Full report context: reporter, reported user profile, call history, prior reports."""
    report_q = await db.execute(select(Report).where(Report.id == report_id))
    report = report_q.scalars().first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    reporter_q = await db.execute(select(User).where(User.id == report.reporter_id))
    reporter = reporter_q.scalars().first()

    reported_q = await db.execute(select(User).where(User.id == report.reported_user_id))
    reported = reported_q.scalars().first()

    # Prior reports against the same user
    prior_q = await db.execute(
        select(Report)
        .where(Report.reported_user_id == report.reported_user_id, Report.id != report_id)
        .order_by(Report.created_at.desc())
    )
    prior_reports = prior_q.scalars().all()

    # Recent calls involving the reported user
    calls_q = await db.execute(
        select(ScheduledCall)
        .where(
            (ScheduledCall.user1_id == report.reported_user_id)
            | (ScheduledCall.user2_id == report.reported_user_id)
        )
        .order_by(ScheduledCall.created_at.desc())
        .limit(10)
    )
    recent_calls = calls_q.scalars().all()

    return {
        "report": {
            "id": report.id,
            "category": report.category,
            "context": report.context,
            "details": report.details,
            "status": report.status,
            "created_at": report.created_at,
            "reviewed_at": report.reviewed_at,
        },
        "reporter": {
            "id": reporter.id if reporter else None,
            "name": reporter.name if reporter else None,
            "email": reporter.email if reporter else None,
        },
        "reported_user": {
            "id": reported.id if reported else None,
            "name": reported.name if reported else None,
            "email": reported.email if reported else None,
            "is_active": reported.is_active if reported else None,
            "strikes": reported.strikes if reported else None,
            "profile_image_url": reported.profile_image_url if reported else None,
        },
        "prior_reports": [
            {"id": r.id, "category": r.category, "context": r.context, "status": r.status, "created_at": r.created_at}
            for r in prior_reports
        ],
        "recent_calls": [
            {
                "id": c.id,
                "status": c.status,
                "scheduled_start_utc": c.scheduled_start_utc,
                "actual_duration_minutes": c.actual_duration_minutes,
            }
            for c in recent_calls
        ],
    }


class ReportActionRequest(BaseModel):
    action: str  # "warn" | "ban" | "dismiss"
    notes: str = ""


@router.post("/reports/{report_id}/action")
async def take_report_action(
    report_id: int,
    body: ReportActionRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Apply a moderation action to a report: warn, ban, or dismiss.

    - warn: increments the reported user's strikes; auto-bans at 3+
    - ban: immediately sets is_active=False
    - dismiss: marks the report dismissed with no user impact
    """
    if body.action not in ("warn", "ban", "dismiss"):
        raise HTTPException(status_code=400, detail="action must be 'warn', 'ban', or 'dismiss'")

    report_q = await db.execute(select(Report).where(Report.id == report_id))
    report = report_q.scalars().first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status == "reviewed":
        raise HTTPException(status_code=409, detail="Report already reviewed")

    reported_q = await db.execute(select(User).where(User.id == report.reported_user_id))
    reported_user = reported_q.scalars().first()

    result_detail = {}
    if body.action == "dismiss":
        report.status = "dismissed"

    elif body.action == "warn":
        report.status = "reviewed"
        if reported_user:
            reported_user.strikes = (reported_user.strikes or 0) + 1
            if reported_user.strikes >= 3:
                reported_user.is_active = False
                result_detail["auto_banned"] = True
            result_detail["strikes_now"] = reported_user.strikes

    elif body.action == "ban":
        report.status = "reviewed"
        if reported_user:
            reported_user.is_active = False
            result_detail["banned"] = True

    report.reviewed_at = datetime.now(timezone.utc)
    report.reviewed_by = admin.id
    await db.commit()

    logger.info(
        f"[ADMIN] Admin {admin.id} took action '{body.action}' on report {report_id} "
        f"(user {report.reported_user_id}). Notes: {body.notes}"
    )
    return {"message": f"Action '{body.action}' applied", "report_id": report_id, **result_detail}


@router.get("/users/{user_id}")
async def get_user_admin_view(
    user_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get full user details for admin review, including report history."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    reports_result = await db.execute(
        select(Report).where(Report.reported_user_id == user_id)
        .order_by(Report.created_at.desc())
    )
    reports = reports_result.scalars().all()

    return {
        "id": target.id,
        "firebase_uid": target.firebase_uid,
        "email": target.email,
        "name": target.name,
        "is_active": target.is_active,
        "is_admin": target.is_admin,
        "strikes": target.strikes,
        "profile_image_url": target.profile_image_url,
        "created_at": None,  # not stored, but field slot reserved
        "reports": [
            {
                "id": r.id,
                "reporter_id": r.reporter_id,
                "category": r.category,
                "context": r.context,
                "details": r.details,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in reports
        ]
    }


# ---------------------------------------------------------------------------
# Birthdate change requests (AGE_VERIFICATION_SPEC.md F5)
# ---------------------------------------------------------------------------
@router.get("/birthdate-change-requests", response_model=list[BirthdateChangeRequestAdminItem])
async def list_birthdate_change_requests(
    status: str = Query("pending", pattern="^(pending|approved|denied)$"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List birthdate-correction requests for admin review (default: pending)."""
    result = await db.execute(
        select(BirthdateChangeRequest, User.name)
        .join(User, User.id == BirthdateChangeRequest.user_id)
        .where(BirthdateChangeRequest.status == status)
        .order_by(BirthdateChangeRequest.submitted_at.asc())
    )
    items = []
    for req, user_name in result.all():
        item = BirthdateChangeRequestAdminItem.model_validate(req)
        item.user_name = user_name
        item.user_current_age = compute_age(req.current_birthdate) if req.current_birthdate else None
        items.append(item)
    return items


@router.post("/birthdate-change-requests/{request_id}/action", response_model=BirthdateChangeRequestAdminItem)
async def action_birthdate_change_request(
    request_id: int,
    body: BirthdateChangeRequestAdminAction,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Approve or deny a pending correction request.

    Approve: atomically updates the user's birthdate + appends an attestation
    (see age_service.approve_birthdate_change). Defense-in-depth: a sub-18
    proposed birthdate is rejected with 422 even here, so an admin can never
    approve an underage account (F5 step 6)."""
    req = (
        await db.execute(
            select(BirthdateChangeRequest).where(BirthdateChangeRequest.id == request_id)
        )
    ).scalars().first()
    if req is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail=f"Request already {req.status}")

    if body.action == "approve":
        try:
            # validate_birthdate runs first inside approve_birthdate_change, before
            # any mutation, so a rejection leaves the session untouched (no rollback).
            req = await approve_birthdate_change(db, req, admin_id=admin.id, note=body.note)
        except BirthdateValidationError as e:
            raise HTTPException(status_code=422, detail=str(e))
        logger.info(f"[ADMIN] Admin {admin.id} approved birthdate request {request_id}")
    else:  # deny
        req.status = "denied"
        req.reviewed_by_admin_id = admin.id
        req.admin_note = body.note
        req.reviewed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(req)
        logger.info(f"[ADMIN] Admin {admin.id} denied birthdate request {request_id}")

    item = BirthdateChangeRequestAdminItem.model_validate(req)
    return item
