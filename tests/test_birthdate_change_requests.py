"""Integration tests for the birthdate-correction flow (AGE_VERIFICATION_SPEC.md
F4/F5), plus schema-level 18+ enforcement on the write paths.

Runs against the Postgres test harness (tests/conftest_pg.py).
"""
from datetime import date

import pytest
from sqlalchemy import func, select

from app import models
from app.limiter import limiter


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    """The create endpoint is limited to 5/day per IP; tests share one IP, so
    disable limiting here to keep cumulative POSTs from tripping a 429."""
    limiter.enabled = False
    yield
    limiter.enabled = True


async def _mk_user(db, name, *, birthdate=None, is_admin=False, uid=None):
    u = models.User(
        firebase_uid=uid or f"uid_{name.lower()}",
        name=name,
        is_active=True,
        is_admin=is_admin,
        birthdate=birthdate,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_create_and_list_request(db, client_as):
    user = await _mk_user(db, "Lena", birthdate=date(2000, 1, 1))
    async with client_as(user) as c:
        r = await c.post("/users/me/birthdate-change-requests",
                         json={"proposed_birthdate": "1995-03-10", "reason": "wrong year"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "pending"
        assert body["proposed_birthdate"] == "1995-03-10"

        r2 = await c.get("/users/me/birthdate-change-requests")
        assert r2.status_code == 200
        assert len(r2.json()) == 1


@pytest.mark.asyncio
async def test_duplicate_pending_returns_409(db, client_as):
    user = await _mk_user(db, "Dup", birthdate=date(2000, 1, 1))
    async with client_as(user) as c:
        r1 = await c.post("/users/me/birthdate-change-requests",
                          json={"proposed_birthdate": "1995-03-10", "reason": "first"})
        assert r1.status_code == 200
        r2 = await c.post("/users/me/birthdate-change-requests",
                          json={"proposed_birthdate": "1994-03-10", "reason": "second"})
        assert r2.status_code == 409


@pytest.mark.asyncio
async def test_no_birthdate_set_returns_400(db, client_as):
    user = await _mk_user(db, "Fresh", birthdate=None)
    async with client_as(user) as c:
        r = await c.post("/users/me/birthdate-change-requests",
                         json={"proposed_birthdate": "1995-03-10", "reason": "x"})
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_proposed_sub_18_rejected_422(db, client_as):
    user = await _mk_user(db, "Teen", birthdate=date(2000, 1, 1))
    async with client_as(user) as c:
        r = await c.post("/users/me/birthdate-change-requests",
                         json={"proposed_birthdate": "2015-01-01", "reason": "nope"})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_admin_approve_updates_birthdate_and_attests(db, client_as):
    user = await _mk_user(db, "Approvee", birthdate=date(2000, 1, 1))
    admin = await _mk_user(db, "Admin", birthdate=date(1990, 1, 1), is_admin=True)

    async with client_as(user) as c:
        r = await c.post("/users/me/birthdate-change-requests",
                         json={"proposed_birthdate": "1995-03-10", "reason": "wrong year"})
        req_id = r.json()["id"]

    async with client_as(admin) as c:
        rlist = await c.get("/admin/birthdate-change-requests?status=pending")
        assert rlist.status_code == 200
        assert any(item["id"] == req_id for item in rlist.json())

        ract = await c.post(f"/admin/birthdate-change-requests/{req_id}/action",
                            json={"action": "approve", "note": "ok"})
        assert ract.status_code == 200, ract.text
        assert ract.json()["status"] == "approved"

    # User birthdate updated + attestation row written.
    refreshed = (await db.execute(select(models.User).where(models.User.id == user.id))).scalars().first()
    assert refreshed.birthdate == date(1995, 3, 10)
    att_count = (await db.execute(
        select(func.count()).select_from(models.AgeAttestation).where(
            models.AgeAttestation.user_id == user.id,
            models.AgeAttestation.source == "admin_approved_change",
        )
    )).scalar()
    assert att_count == 1


@pytest.mark.asyncio
async def test_admin_deny_leaves_birthdate_unchanged(db, client_as):
    user = await _mk_user(db, "Denyee", birthdate=date(2000, 1, 1))
    admin = await _mk_user(db, "Admin2", birthdate=date(1990, 1, 1), is_admin=True)

    async with client_as(user) as c:
        r = await c.post("/users/me/birthdate-change-requests",
                         json={"proposed_birthdate": "1995-03-10", "reason": "x"})
        req_id = r.json()["id"]

    async with client_as(admin) as c:
        ract = await c.post(f"/admin/birthdate-change-requests/{req_id}/action",
                            json={"action": "deny", "note": "suspicious"})
        assert ract.status_code == 200
        assert ract.json()["status"] == "denied"

    refreshed = (await db.execute(select(models.User).where(models.User.id == user.id))).scalars().first()
    assert refreshed.birthdate == date(2000, 1, 1)  # unchanged


@pytest.mark.asyncio
async def test_admin_cannot_approve_sub_18(db, client_as):
    """A pending request with a sub-18 proposed birthdate (inserted directly,
    bypassing request-time validation) must still be rejected at approve time."""
    user = await _mk_user(db, "Sneaky", birthdate=date(2000, 1, 1))
    admin = await _mk_user(db, "Admin3", birthdate=date(1990, 1, 1), is_admin=True)

    bad = models.BirthdateChangeRequest(
        user_id=user.id,
        current_birthdate=date(2000, 1, 1),
        proposed_birthdate=date(2015, 1, 1),  # sub-18
        reason="bypass",
        status="pending",
    )
    db.add(bad)
    await db.commit()
    await db.refresh(bad)

    async with client_as(admin) as c:
        ract = await c.post(f"/admin/birthdate-change-requests/{bad.id}/action",
                            json={"action": "approve"})
        assert ract.status_code == 422

    # State unchanged: user birthdate intact, request still pending.
    refreshed_user = (await db.execute(select(models.User).where(models.User.id == user.id))).scalars().first()
    assert refreshed_user.birthdate == date(2000, 1, 1)
    refreshed_req = (await db.execute(
        select(models.BirthdateChangeRequest).where(models.BirthdateChangeRequest.id == bad.id)
    )).scalars().first()
    assert refreshed_req.status == "pending"


@pytest.mark.asyncio
async def test_non_admin_cannot_list(db, client_as):
    user = await _mk_user(db, "Plain", birthdate=date(2000, 1, 1))
    async with client_as(user) as c:
        r = await c.get("/admin/birthdate-change-requests?status=pending")
        assert r.status_code == 403


# --- schema-level 18+ enforcement on the user-create + profile-update paths ---
# `nodb` + async so the legacy autouse SQLite fixture skips (see test_age_service).
@pytest.mark.nodb
async def test_user_create_request_rejects_sub_18():
    from app.routers.users import UserCreateRequest
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        UserCreateRequest(firebase_uid="x", email="a@b.com", birthdate=date(2015, 1, 1))


@pytest.mark.nodb
async def test_user_create_request_accepts_adult():
    from app.routers.users import UserCreateRequest
    req = UserCreateRequest(firebase_uid="x", email="a@b.com", birthdate=date(2000, 1, 1))
    assert req.birthdate == date(2000, 1, 1)


@pytest.mark.nodb
async def test_profile_update_rejects_age_field():
    from app.schemas import ProfileUpdate
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        ProfileUpdate(age=25)
