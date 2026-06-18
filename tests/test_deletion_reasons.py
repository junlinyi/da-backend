"""POST /deletion-reasons — anonymous churn capture + validation (Pydantic and
the mirrored DB CHECK constraint). Runs against the Postgres harness.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import models
from app.main import app
from app.database import get_db
from app.dependencies import verify_firebase_token
from app.limiter import limiter

limiter.enabled = False  # the 1/minute cap would block repeated POSTs in a test


def _client(db, firebase_uid="uid_x"):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[verify_firebase_token] = lambda: {"uid": firebase_uid}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.parametrize("reason", ["found_someone", "not_finding_matches", "privacy", "bugs"])
async def test_record_reason_without_text(db, reason):
    async with _client(db) as c:
        r = await c.post("/deletion-reasons", json={"reason": reason})
    assert r.status_code == 204, r.text
    rows = (await db.execute(select(models.DeletionReason))).scalars().all()
    assert len(rows) == 1
    assert rows[0].reason == reason
    assert rows[0].free_text is None
    # No user identifier persisted (DD-5: anonymous, retention-free).
    assert not hasattr(rows[0], "user_id")


async def test_other_requires_free_text_returns_422(db):
    async with _client(db) as c:
        r = await c.post("/deletion-reasons", json={"reason": "other"})
    assert r.status_code == 422
    rows = (await db.execute(select(models.DeletionReason))).scalars().all()
    assert rows == []


async def test_other_with_free_text_persists(db):
    async with _client(db) as c:
        r = await c.post("/deletion-reasons",
                         json={"reason": "other", "free_text": "switching to a different app"})
    assert r.status_code == 204, r.text
    rows = (await db.execute(select(models.DeletionReason))).scalars().all()
    assert rows[0].reason == "other"
    assert rows[0].free_text == "switching to a different app"


async def test_free_text_dropped_for_non_other(db):
    async with _client(db) as c:
        r = await c.post("/deletion-reasons", json={"reason": "bugs", "free_text": "ignored"})
    assert r.status_code == 204, r.text
    rows = (await db.execute(select(models.DeletionReason))).scalars().all()
    assert rows[0].free_text is None


async def test_invalid_reason_returns_422(db):
    async with _client(db) as c:
        r = await c.post("/deletion-reasons", json={"reason": "lol_nope"})
    assert r.status_code == 422


async def test_db_check_constraint_blocks_other_without_text(db):
    """Defense in depth: even if Pydantic were bypassed, the DB CHECK rejects
    an 'other' row with no free_text."""
    db.add(models.DeletionReason(reason="other", free_text=None))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
