"""PhotoScanLog audit row persists against the Postgres harness."""
import pytest
from sqlalchemy import select

from app import models

pytestmark = pytest.mark.asyncio


async def test_photo_scan_log_roundtrip(db, make_user):
    u = await make_user(name="Scan", firebase_uid="uid_scan")
    row = models.PhotoScanLog(
        user_id=u.id,
        image_url="https://firebasestorage.googleapis.com/v0/b/x/o/p?alt=media&token=t",
        decision="block",
        scores={"adult": 5, "violence": 0},
    )
    db.add(row)
    await db.flush()
    fetched = (await db.execute(
        select(models.PhotoScanLog).where(models.PhotoScanLog.user_id == u.id)
    )).scalars().first()
    assert fetched.decision == "block"
    assert fetched.scores["adult"] == 5
    assert fetched.created_at is not None


async def test_photo_scan_log_allows_null_user(db):
    # Brand-new-signup block happens before a user id exists.
    row = models.PhotoScanLog(
        user_id=None,
        image_url="https://firebasestorage.googleapis.com/x",
        decision="block",
        scores={},
    )
    db.add(row)
    await db.flush()
    assert row.id is not None
