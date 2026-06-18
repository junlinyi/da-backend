"""DELETE /users/{id} — GDPR PII scrub, idempotency, authorization, and
conversation deactivation. Runs against the Postgres harness (conftest_pg.py)
so ARRAY columns and real constraints behave as in production.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app import models
from app.main import app
from app.database import get_db
from app.dependencies import verify_firebase_token
from app.limiter import limiter

# Repeated DELETEs from one test-client IP must not hit the 3/hour cap.
limiter.enabled = False


def _client(db, firebase_uid):
    """AsyncClient authed as `firebase_uid` (the DELETE endpoint reads the token
    dict via verify_firebase_token, not get_current_user)."""
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[verify_firebase_token] = lambda: {"uid": firebase_uid}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


async def test_delete_scrubs_all_pii(db, make_user):
    u = await make_user(name="Andrew", firebase_uid="uid_andrew", device_token="tok123")
    u.email = "andrew@example.com"
    u.phone_number = "+15555550001"
    u.phone_country_code = "+1"
    u.bio = "hello world"
    u.gender = "male"
    u.interests = ["coding", "hiking"]
    u.location = "San Francisco"
    u.state = "CA"
    u.latitude = 37.7
    u.longitude = -122.4
    u.age = 25
    u.preferred_gender = "female"
    u.min_age_preference = 21
    u.max_age_preference = 40
    u.profile_image_url = "http://img/1.jpg"
    u.additional_image_urls = ["http://img/2.jpg"]
    u.prompts = {"q": "a"}
    await db.commit()
    uid = u.id

    async with _client(db, "uid_andrew") as c:
        r = await c.delete(f"/users/{uid}")
    assert r.status_code == 200, r.text

    db.expire_all()  # force a real DB read, not the identity-map copy
    row = (await db.execute(select(models.User).where(models.User.id == uid))).scalars().first()
    assert row.deleted_at is not None
    assert row.is_active is False
    assert row.firebase_uid == f"deleted:{uid}"
    assert row.email == f"deleted_{uid}@deleted.invalid"
    assert row.phone_number == f"deleted_{uid}_phone"
    assert row.phone_country_code is None
    assert row.name == "Deleted User"
    assert row.bio is None
    assert row.gender is None
    assert row.interests == []
    assert row.location is None
    assert row.state is None
    assert row.latitude is None and row.longitude is None
    assert row.preferred_gender is None
    assert row.min_age_preference is None and row.max_age_preference is None
    assert row.device_token is None
    assert row.profile_image_url is None
    assert row.additional_image_urls is None
    assert row.prompts is None
    # Defensive age branch: pre-merge `age` is a settable column, so it is nulled.
    assert row.age is None


async def test_delete_is_idempotent_returns_404_second_time(db, make_user):
    u = await make_user(name="Bo", firebase_uid="uid_bo")
    uid = u.id
    async with _client(db, "uid_bo") as c:
        r1 = await c.delete(f"/users/{uid}")
        assert r1.status_code == 200, r1.text
        # Row is now soft-deleted; the active-row filter makes a repeat a 404.
        r2 = await c.delete(f"/users/{uid}")
    assert r2.status_code == 404


async def test_cannot_delete_another_users_account_403(db, make_user):
    victim = await make_user(name="Vic", firebase_uid="uid_victim")
    vid = victim.id  # capture before expire_all (async-safe)
    async with _client(db, "uid_attacker") as c:
        r = await c.delete(f"/users/{vid}")
    assert r.status_code == 403
    db.expire_all()
    row = (await db.execute(select(models.User).where(models.User.id == vid))).scalars().first()
    assert row.deleted_at is None  # untouched


async def test_delete_unknown_user_404(db):
    async with _client(db, "uid_ghost") as c:
        r = await c.delete("/users/999999")
    assert r.status_code == 404


async def test_delete_deactivates_all_user_conversations(db, make_user):
    a = await make_user(name="A", firebase_uid="uid_a")
    b = await make_user(name="B", firebase_uid="uid_b")
    c2 = await make_user(name="C", firebase_uid="uid_c")
    conv_ab = models.Conversation(user1_id=a.id, user2_id=b.id, is_active=True)
    conv_ca = models.Conversation(user1_id=c2.id, user2_id=a.id, is_active=True)  # a on user2 side
    conv_bc = models.Conversation(user1_id=b.id, user2_id=c2.id, is_active=True)  # not a's
    db.add_all([conv_ab, conv_ca, conv_bc])
    await db.commit()
    ab_id, ca_id, bc_id, a_id = conv_ab.id, conv_ca.id, conv_bc.id, a.id

    async with _client(db, "uid_a") as c:
        r = await c.delete(f"/users/{a_id}")
    assert r.status_code == 200, r.text

    db.expire_all()
    rows = {row.id: row.is_active for row in
            (await db.execute(select(models.Conversation))).scalars().all()}
    assert rows[ab_id] is False
    assert rows[ca_id] is False
    assert rows[bc_id] is True  # conversation a is not part of stays active
