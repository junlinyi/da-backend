# app/services/age_service.py
"""Age-verification service (AGE_VERIFICATION_SPEC.md).

Single source of truth for deriving age from a birthdate, validating the 18+
rule on every write path, and recording the append-only attestation trail.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models import AgeAttestation, BirthdateChangeRequest, User

MIN_AGE = 18
MAX_AGE = 120

# User-facing copy reused by the API + Pydantic validators so the message is
# identical everywhere a sub-18 birthdate is rejected.
UNDER_18_MESSAGE = "Our community is 18+. Please check your birthday."


class BirthdateValidationError(ValueError):
    """Raised when a birthdate fails the 18+/sanity rules. Carries a
    user-facing message suitable for an HTTP 422 detail."""


def compute_age(birthdate: date, today: date | None = None) -> int:
    """Full-year age from a birthdate (DD-9). A user born 2008-05-01 is 18 on
    2008+18=2026-05-01, NOT on 2026-01-01."""
    today = today or date.today()
    return today.year - birthdate.year - (
        (today.month, today.day) < (birthdate.month, birthdate.day)
    )


def _subtract_years(d: date, years: int) -> date:
    """d minus `years`, clamping Feb 29 to Feb 28 in non-leap target years."""
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        return d.replace(year=d.year - years, day=28)


def birthdate_bounds_for_age_range(
    min_age: int, max_age: int, today: date | None = None
) -> tuple[date, date]:
    """Convert an inclusive [min_age, max_age] preference into an inclusive
    birthdate range usable in a SQL ``birthdate BETWEEN lower AND upper``.

    age >= min_age  ⟺  birthdate <= today - min_age years          (upper bound)
    age <= max_age  ⟺  birthdate >= today - (max_age+1) years + 1d  (lower bound)
    """
    today = today or date.today()
    upper = _subtract_years(today, min_age)
    lower = _subtract_years(today, max_age + 1) + timedelta(days=1)
    return lower, upper


def validate_birthdate(birthdate: date, today: date | None = None) -> None:
    """Raise BirthdateValidationError unless birthdate implies a sane 18+ age.

    Rejects: future dates, ages > 120, ages < 18. Accepts exactly-18."""
    today = today or date.today()
    if birthdate > today:
        raise BirthdateValidationError("Birthday cannot be in the future. Please check your birthday.")
    age = compute_age(birthdate, today)
    if age > MAX_AGE:
        raise BirthdateValidationError("Please check your birthday.")
    if age < MIN_AGE:
        raise BirthdateValidationError(UNDER_18_MESSAGE)


async def record_attestation(
    db: AsyncSession,
    user_id: int,
    birthdate: date,
    source: str,
    admin_id: int | None = None,
    change_request_id: int | None = None,
) -> AgeAttestation:
    """Append an age-attestation row. Caller owns the transaction (no commit here)
    so signup / admin-approve can write the user + attestation atomically."""
    attestation = AgeAttestation(
        user_id=user_id,
        birthdate=birthdate,
        source=source,
        admin_id=admin_id,
        change_request_id=change_request_id,
    )
    db.add(attestation)
    return attestation


async def approve_birthdate_change(
    db: AsyncSession,
    request: BirthdateChangeRequest,
    admin_id: int,
    note: str | None = None,
) -> BirthdateChangeRequest:
    """Approve a pending correction request inside a single transaction: flip the
    request to approved, update the user's birthdate, and append an attestation.

    Defense-in-depth: re-validates 18+ here so an admin can never approve a sub-18
    birthdate even if a row bypassed request-time validation (DD-4, F5 step 6)."""
    from datetime import datetime, timezone

    validate_birthdate(request.proposed_birthdate)

    user = (
        await db.execute(select(User).where(User.id == request.user_id))
    ).scalars().first()
    if user is None:
        raise BirthdateValidationError("User no longer exists.")

    user.birthdate = request.proposed_birthdate
    request.status = "approved"
    request.reviewed_by_admin_id = admin_id
    request.admin_note = note
    request.reviewed_at = datetime.now(timezone.utc)

    await record_attestation(
        db,
        user_id=user.id,
        birthdate=request.proposed_birthdate,
        source="admin_approved_change",
        admin_id=admin_id,
        change_request_id=request.id,
    )
    await db.commit()
    await db.refresh(request)
    return request
