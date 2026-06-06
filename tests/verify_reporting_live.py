"""
Live verification of structured reporting against the real Postgres DB.

The shared pytest harness (tests/conftest.py) targets SQLite, which can't
render the `users.interests` ARRAY column, and several existing test modules
have stale model imports — so it can't run as-is. This standalone script drives
the full FastAPI stack (TestClient) against the actual Postgres database with
auth stubbed, exercising every case in REPORTING_CATEGORIES_SPEC.md's test
plan, then cleans up the rows it created.

Run: python -m tests.verify_reporting_live   (with the venv active)
"""
import asyncio
import sys

import httpx
from sqlalchemy import select, delete

from app.main import app
from app.database import SessionLocal
from app.dependencies import verify_firebase_token
from app.limiter import limiter
from app.models import User, Report

limiter.enabled = False

_state = {"uid": "verify_reporter"}
app.dependency_overrides[verify_firebase_token] = lambda: {"uid": _state["uid"]}

PREFIX = "verify_report_"
CATEGORIES = [
    "harassment", "inappropriate_photos", "explicit_on_video_call",
    "underage", "impersonation", "scam_spam", "hate_speech",
    "violence_threat", "off_platform_solicitation", "other",
]

passed, failed = 0, 0


def check(label, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {label}")
    else:
        failed += 1
        print(f"  ✗ {label}  {extra}")


async def seed_users():
    async with SessionLocal() as s:
        # reporter + 12 targets
        uids = [f"{PREFIX}reporter"] + [f"{PREFIX}target_{i}" for i in range(12)]
        existing = (await s.execute(select(User.firebase_uid).where(User.firebase_uid.in_(uids)))).scalars().all()
        for uid in uids:
            if uid not in existing:
                s.add(User(firebase_uid=uid, name=uid, is_active=True))
        await s.commit()


async def cleanup():
    async with SessionLocal() as s:
        ids = (await s.execute(select(User.id).where(User.firebase_uid.like(f"{PREFIX}%")))).scalars().all()
        if ids:
            await s.execute(delete(Report).where(
                (Report.reporter_id.in_(ids)) | (Report.reported_user_id.in_(ids))
            ))
            await s.execute(delete(User).where(User.id.in_(ids)))
            await s.commit()


def auth(uid):
    return {"Authorization": f"Bearer {uid}"}


async def run_http_checks(client):
    _state["uid"] = f"{PREFIX}reporter"
    rep = auth(f"{PREFIX}reporter")

    # 1. All 10 categories accepted (distinct target each → no dedupe)
    for i, cat in enumerate(CATEGORIES):
        body = {"reported_firebase_uid": f"{PREFIX}target_{i}", "category": cat, "context": "profile"}
        if cat == "other":
            body["details"] = "A specific long-tail issue worth describing."
        r = await client.post("/reports", json=body, headers=rep)
        check(f"category {cat} → 201", r.status_code == 201, r.text)

    # 2. Unknown category → 422
    r = await client.post("/reports", json={"reported_firebase_uid": f"{PREFIX}target_10", "category": "nope", "context": "chat"}, headers=rep)
    check("unknown category → 422", r.status_code == 422, r.text)

    # 3. Invalid context → 422
    r = await client.post("/reports", json={"reported_firebase_uid": f"{PREFIX}target_10", "category": "harassment", "context": "billboard"}, headers=rep)
    check("invalid context → 422", r.status_code == 422, r.text)

    # 4. other without details → 422
    r = await client.post("/reports", json={"reported_firebase_uid": f"{PREFIX}target_10", "category": "other", "context": "chat"}, headers=rep)
    check("other w/o details → 422", r.status_code == 422, r.text)

    # 5. other with short details → 422
    r = await client.post("/reports", json={"reported_firebase_uid": f"{PREFIX}target_10", "category": "other", "context": "chat", "details": "short"}, headers=rep)
    check("other w/ short details → 422", r.status_code == 422, r.text)

    # 6. Dedupe: second report on same pair within 24h → 409
    r = await client.post("/reports", json={"reported_firebase_uid": f"{PREFIX}target_11", "category": "harassment", "context": "chat"}, headers=rep)
    check("first report on target_11 → 201", r.status_code == 201, r.text)
    r = await client.post("/reports", json={"reported_firebase_uid": f"{PREFIX}target_11", "category": "scam_spam", "context": "video_call"}, headers=rep)
    check("dup report (cross-context) → 409", r.status_code == 409, r.text)

    # 7. Cannot report self → 400
    r = await client.post("/reports", json={"reported_firebase_uid": f"{PREFIX}reporter", "category": "harassment", "context": "chat"}, headers=rep)
    check("report self → 400", r.status_code == 400, r.text)


async def main():
    await cleanup()  # clean any leftovers from a prior run
    await seed_users()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await run_http_checks(client)
    finally:
        await cleanup()
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
