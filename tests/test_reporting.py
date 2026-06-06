"""
Tests for structured reporting (REPORTING_CATEGORIES_SPEC.md).

Covers: POST /reports accepts all 10 categories, rejects unknown categories,
rejects `other` without (sufficient) details, enforces the 24h per-pair dedupe
(409), and blocks self-reports (400).

Auth is stubbed by overriding `verify_firebase_token` so the bearer token IS
the firebase uid. The slowapi limiter is disabled so repeated POSTs in one test
run don't trip the 20/hour cap.
"""
import pytest
from app.main import app
from app.dependencies import verify_firebase_token
from app.limiter import limiter
from app.models import User
from tests.conftest import test_db_instance

# Repeated POSTs from the same test-client IP must not hit the 20/hour cap.
limiter.enabled = False

ALL_CATEGORIES = [
    "harassment", "inappropriate_photos", "explicit_on_video_call",
    "underage", "impersonation", "scam_spam", "hate_speech",
    "violence_threat", "off_platform_solicitation", "other",
]


def _auth(uid: str) -> dict:
    return {"Authorization": f"Bearer {uid}"}


@pytest.fixture(autouse=True)
def _override_auth():
    # Treat the bearer token as the firebase uid directly.
    app.dependency_overrides[verify_firebase_token] = lambda: {"uid": _override_auth.current_uid}
    _override_auth.current_uid = "reporter_uid"
    yield
    app.dependency_overrides.pop(verify_firebase_token, None)


async def _seed_user(firebase_uid: str, name: str) -> User:
    async with test_db_instance.async_session() as session:
        user = User(firebase_uid=firebase_uid, name=name, is_active=True)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.mark.asyncio
async def test_all_categories_accepted(test_db, client):
    """All 10 categories POST successfully (one distinct target each to dodge dedupe)."""
    await _seed_user("rep_cat", "Reporter Cat")
    _override_auth.current_uid = "rep_cat"

    for i, category in enumerate(ALL_CATEGORIES):
        target_uid = f"target_cat_{i}"
        await _seed_user(target_uid, f"Target {i}")
        body = {"reported_firebase_uid": target_uid, "category": category, "context": "profile"}
        if category == "other":
            body["details"] = "Specific long-tail thing worth describing here."
        resp = client.post("/reports", json=body, headers=_auth("rep_cat"))
        assert resp.status_code == 201, (category, resp.text)
        data = resp.json()
        assert data["category"] == category
        assert data["context"] == "profile"


@pytest.mark.asyncio
async def test_unknown_category_rejected(test_db, client):
    await _seed_user("rep_bad", "Reporter Bad")
    await _seed_user("target_bad", "Target Bad")
    _override_auth.current_uid = "rep_bad"
    resp = client.post(
        "/reports",
        json={"reported_firebase_uid": "target_bad", "category": "not_a_real_category", "context": "chat"},
        headers=_auth("rep_bad"),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_invalid_context_rejected(test_db, client):
    await _seed_user("rep_ctx", "Reporter Ctx")
    await _seed_user("target_ctx", "Target Ctx")
    _override_auth.current_uid = "rep_ctx"
    resp = client.post(
        "/reports",
        json={"reported_firebase_uid": "target_ctx", "category": "harassment", "context": "billboard"},
        headers=_auth("rep_ctx"),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_other_requires_details(test_db, client):
    await _seed_user("rep_other", "Reporter Other")
    await _seed_user("target_other", "Target Other")
    _override_auth.current_uid = "rep_other"

    # Missing details → 422
    resp = client.post(
        "/reports",
        json={"reported_firebase_uid": "target_other", "category": "other", "context": "chat"},
        headers=_auth("rep_other"),
    )
    assert resp.status_code == 422, resp.text

    # Too-short details → 422
    resp = client.post(
        "/reports",
        json={"reported_firebase_uid": "target_other", "category": "other", "context": "chat", "details": "short"},
        headers=_auth("rep_other"),
    )
    assert resp.status_code == 422, resp.text

    # Sufficient details → 201
    resp = client.post(
        "/reports",
        json={
            "reported_firebase_uid": "target_other", "category": "other", "context": "chat",
            "details": "Weird emoji pattern in bio that feels threatening.",
        },
        headers=_auth("rep_other"),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["details"].startswith("Weird emoji")


@pytest.mark.asyncio
async def test_dedupe_within_24h(test_db, client):
    await _seed_user("rep_dup", "Reporter Dup")
    await _seed_user("target_dup", "Target Dup")
    _override_auth.current_uid = "rep_dup"
    body = {"reported_firebase_uid": "target_dup", "category": "harassment", "context": "chat"}

    first = client.post("/reports", json=body, headers=_auth("rep_dup"))
    assert first.status_code == 201, first.text

    second = client.post("/reports", json=body, headers=_auth("rep_dup"))
    assert second.status_code == 409, second.text
    assert "already reported" in second.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cannot_report_self(test_db, client):
    await _seed_user("rep_self", "Reporter Self")
    _override_auth.current_uid = "rep_self"
    resp = client.post(
        "/reports",
        json={"reported_firebase_uid": "rep_self", "category": "harassment", "context": "chat"},
        headers=_auth("rep_self"),
    )
    assert resp.status_code == 400, resp.text
