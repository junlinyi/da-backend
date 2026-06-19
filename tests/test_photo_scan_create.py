"""POST /users/create enforces SafeSearch on profile photos."""
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app import models
from app.main import app
from app.database import get_db
from app.dependencies import verify_firebase_token
from app.services import photo_moderation_service as pm
from app.services.photo_moderation_service import ModerationResult

pytestmark = pytest.mark.asyncio
FB = "https://firebasestorage.googleapis.com/v0/b/x/o/p?alt=media&token=t"


def _client(db, uid):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[verify_firebase_token] = lambda: {"uid": uid}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


async def test_create_blocks_explicit_photo(db, monkeypatch):
    async def _block(url):
        return ModerationResult(
            False, "block", "This photo can't be used. Please choose a different one.", {"adult": 5})
    monkeypatch.setattr(pm, "scan_image_url", _block)

    async with _client(db, "uid_block") as c:
        r = await c.post("/users/create", json={
            "firebase_uid": "uid_block", "email": "b@x.com", "profile_image_url": FB,
        })
    assert r.status_code == 422
    # nothing persisted
    user = (await db.execute(
        select(models.User).where(models.User.firebase_uid == "uid_block"))).scalars().first()
    assert user is None
    # a block log row exists
    log = (await db.execute(
        select(models.PhotoScanLog).where(models.PhotoScanLog.decision == "block"))).scalars().first()
    assert log is not None and log.image_url == FB


async def test_create_allows_clean_photo_and_logs_pass(db, monkeypatch):
    async def _pass(url):
        return ModerationResult(True, "pass", None, {"adult": 1})
    monkeypatch.setattr(pm, "scan_image_url", _pass)

    async with _client(db, "uid_ok") as c:
        r = await c.post("/users/create", json={
            "firebase_uid": "uid_ok", "email": "ok@x.com", "profile_image_url": FB,
        })
    assert r.status_code == 200
    user = (await db.execute(
        select(models.User).where(models.User.firebase_uid == "uid_ok"))).scalars().first()
    assert user is not None and user.profile_image_url == FB
    log = (await db.execute(
        select(models.PhotoScanLog).where(models.PhotoScanLog.decision == "pass"))).scalars().first()
    assert log is not None


async def test_create_scans_additional_images(db, monkeypatch):
    seen = []

    async def _spy(url):
        seen.append(url)
        return ModerationResult(True, "pass", None, {})
    monkeypatch.setattr(pm, "scan_image_url", _spy)

    async with _client(db, "uid_multi") as c:
        r = await c.post("/users/create", json={
            "firebase_uid": "uid_multi", "email": "m@x.com",
            "profile_image_url": FB, "additional_image_urls": f"{FB},{FB}2",
        })
    assert r.status_code == 200
    assert len(seen) == 3
