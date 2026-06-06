"""
Tests for admin report listing/detail with the structured category/context
fields (REPORTING_CATEGORIES_SPEC.md): filter by category + context, and the
detail endpoint surfaces category/context/details (not the legacy `reason`).
"""
import pytest
from app.main import app
from app.dependencies import verify_firebase_token
from app.models import User, Report
from tests.conftest import test_db_instance


def _auth(uid: str) -> dict:
    return {"Authorization": f"Bearer {uid}"}


@pytest.fixture(autouse=True)
def _override_auth():
    app.dependency_overrides[verify_firebase_token] = lambda: {"uid": _override_auth.current_uid}
    _override_auth.current_uid = "admin_uid"
    yield
    app.dependency_overrides.pop(verify_firebase_token, None)


async def _seed_user(firebase_uid: str, name: str, is_admin: bool = False) -> User:
    async with test_db_instance.async_session() as session:
        user = User(firebase_uid=firebase_uid, name=name, is_active=True, is_admin=is_admin)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _seed_report(reporter_id, reported_id, category, context, details=None) -> int:
    async with test_db_instance.async_session() as session:
        r = Report(
            reporter_id=reporter_id, reported_user_id=reported_id,
            category=category, context=context, details=details, status="pending",
        )
        session.add(r)
        await session.commit()
        await session.refresh(r)
        return r.id


@pytest.mark.asyncio
async def test_filter_by_category_and_context(test_db, client):
    admin = await _seed_user("admin_filter", "Admin", is_admin=True)
    reporter = await _seed_user("reporter_filter", "Reporter")
    reported = await _seed_user("reported_filter", "Reported")
    _override_auth.current_uid = "admin_filter"

    await _seed_report(reporter.id, reported.id, "harassment", "chat")
    await _seed_report(reporter.id, reported.id, "underage", "video_call")
    await _seed_report(reporter.id, reported.id, "scam_spam", "profile")

    # Filter by category
    resp = client.get("/admin/reports?status=all&category=underage", headers=_auth("admin_filter"))
    assert resp.status_code == 200, resp.text
    cats = {r["category"] for r in resp.json()}
    assert cats == {"underage"}

    # Filter by context
    resp = client.get("/admin/reports?status=all&context=video_call", headers=_auth("admin_filter"))
    assert resp.status_code == 200, resp.text
    ctxs = {r["context"] for r in resp.json()}
    assert ctxs == {"video_call"}


@pytest.mark.asyncio
async def test_detail_returns_category_context(test_db, client):
    admin = await _seed_user("admin_detail", "Admin", is_admin=True)
    reporter = await _seed_user("reporter_detail", "Reporter")
    reported = await _seed_user("reported_detail", "Reported")
    _override_auth.current_uid = "admin_detail"

    rid = await _seed_report(
        reporter.id, reported.id, "off_platform_solicitation", "chat",
        details="Asked for my number repeatedly.",
    )

    resp = client.get(f"/admin/reports/{rid}", headers=_auth("admin_detail"))
    assert resp.status_code == 200, resp.text
    report = resp.json()["report"]
    assert report["category"] == "off_platform_solicitation"
    assert report["context"] == "chat"
    assert report["details"] == "Asked for my number repeatedly."
    assert "reason" not in report


@pytest.mark.asyncio
async def test_non_admin_forbidden(test_db, client):
    await _seed_user("plain_user", "Plain", is_admin=False)
    _override_auth.current_uid = "plain_user"
    resp = client.get("/admin/reports", headers=_auth("plain_user"))
    assert resp.status_code == 403, resp.text
