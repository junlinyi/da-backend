"""PUT /users/me/profile scans a changed profile photo (scan-on-change)."""
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_db
from app.dependencies import verify_firebase_token
from app.services import photo_moderation_service as pm
from app.services.photo_moderation_service import ModerationResult

pytestmark = pytest.mark.asyncio
FB = "https://firebasestorage.googleapis.com/v0/b/x/o/new?alt=media&token=t"


def _client(db, uid):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[verify_firebase_token] = lambda: {"uid": uid}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


async def test_profile_blocks_explicit_new_photo(db, make_user, monkeypatch):
    u = await make_user(name="P", firebase_uid="uid_p")

    async def _block(url):
        return ModerationResult(
            False, "block", "This photo can't be used. Please choose a different one.", {})
    monkeypatch.setattr(pm, "scan_image_url", _block)

    async with _client(db, "uid_p") as c:
        r = await c.put("/users/me/profile", json={"profileImageURL": FB})
    assert r.status_code == 422
    await db.refresh(u)
    assert u.profile_image_url != FB


async def test_profile_unchanged_photo_not_scanned(db, make_user, monkeypatch):
    u = await make_user(name="P2", firebase_uid="uid_p2")
    u.profile_image_url = FB
    await db.flush()
    called = {"n": 0}

    async def _spy(url):
        called["n"] += 1
        return ModerationResult(True, "pass", None, {})
    monkeypatch.setattr(pm, "scan_image_url", _spy)

    async with _client(db, "uid_p2") as c:
        r = await c.put("/users/me/profile", json={"profileImageURL": FB, "bio": "hi"})
    assert r.status_code == 200
    assert called["n"] == 0  # same URL -> no scan
