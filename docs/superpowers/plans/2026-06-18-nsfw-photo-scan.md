# NSFW Photo Scan on Upload — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scan every newly-set profile photo with Google Cloud Vision SafeSearch and hard-block the profile save (HTTP 422) when a photo is explicit/violent, with a durable audit trail.

**Architecture:** A new pure-decision helper + an async Vision wrapper live in `app/services/photo_moderation_service.py` (mirroring the stable-interface convention of `chat_message_filter.py`). Two write endpoints in `app/routers/users.py` (`POST /users/create`, `PUT /users/me/profile`) call a shared helper that scans each changed photo URL, writes a `photo_scan_log` row per scan, and raises 422 on a block. Vision fetches the image from the client-supplied Firebase Storage URL itself (`ImageSource.image_uri`), so the backend never downloads bytes.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, `google-cloud-vision`, pytest (real-Postgres harness `conftest_pg.py` + `nodb` unit marker).

## Global Constraints

- Python 3.13; async SQLAlchemy; Pydantic v2.
- Timezone: always `datetime.now(timezone.utc)`, never `datetime.utcnow()`.
- NEVER modify `.env` or credential files; NEVER hardcode secrets. Read config via `os.getenv(...)` at module top level (no Settings class exists).
- ALWAYS work on branch `feature/nsfw-photo-scan` (already created off `main`).
- Audit table mirrors the `AgeAttestation` pattern (`app/models.py:102`).
- Decision policy: **block** if `adult >= LIKELY` OR `violence >= LIKELY`; **allow** `racy` at any level. Thresholds env-tunable.
- Failure mode: retry once, then **fail-open** (allow), log `decision="error"`, report to Sentry.
- Kill-switch: `PHOTO_SCAN_ENABLED` false ⇒ immediate pass, no Vision call.
- Spec: `docs/superpowers/specs/2026-06-18-nsfw-photo-scan-design.md`.

---

### Task 1: Decision core + config (pure, no I/O)

The testable heart: the `Likelihood` mapping, env thresholds, the `ModerationResult` dataclass, and `evaluate_safesearch()` which turns a scores dict into an allow/block decision. No DB, no network.

**Files:**
- Create: `app/services/photo_moderation_service.py`
- Test: `tests/test_photo_moderation_unit.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `LIKELIHOOD: dict[str, int]` — `{"UNKNOWN":0,"VERY_UNLIKELY":1,"UNLIKELY":2,"POSSIBLE":3,"LIKELY":4,"VERY_LIKELY":5}`
  - `@dataclass ModerationResult: allowed: bool; status: str; reason: str | None; scores: dict`
  - `evaluate_safesearch(scores: dict[str, int], *, adult_threshold: int, violence_threshold: int) -> ModerationResult`
  - `PHOTO_SCAN_ENABLED: bool`, `ADULT_THRESHOLD: int`, `VIOLENCE_THRESHOLD: int` (module-level, from env)

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/test_photo_moderation_unit.py
import pytest
from app.services.photo_moderation_service import (
    evaluate_safesearch, ModerationResult, LIKELIHOOD,
)

# Pure unit tests — no DB. Opt out of the SQLite autouse harness fixtures.
pytestmark = pytest.mark.nodb

L = LIKELIHOOD
DEFAULTS = {"adult_threshold": L["LIKELY"], "violence_threshold": L["LIKELY"]}


def _scores(adult="VERY_UNLIKELY", violence="VERY_UNLIKELY", racy="VERY_UNLIKELY"):
    return {"adult": L[adult], "violence": L[violence], "racy": L[racy]}


def test_clean_photo_allowed():
    r = evaluate_safesearch(_scores(), **DEFAULTS)
    assert isinstance(r, ModerationResult)
    assert r.allowed is True and r.status == "pass" and r.reason is None


@pytest.mark.parametrize("level", ["LIKELY", "VERY_LIKELY"])
def test_adult_at_or_above_threshold_blocks(level):
    r = evaluate_safesearch(_scores(adult=level), **DEFAULTS)
    assert r.allowed is False and r.status == "block" and r.reason


def test_adult_below_threshold_allowed():
    r = evaluate_safesearch(_scores(adult="POSSIBLE"), **DEFAULTS)
    assert r.allowed is True and r.status == "pass"


def test_violence_at_threshold_blocks():
    r = evaluate_safesearch(_scores(violence="LIKELY"), **DEFAULTS)
    assert r.allowed is False and r.status == "block"


def test_racy_very_likely_allowed_swimwear_case():
    # Dating photos routinely rate racy; must NOT block.
    r = evaluate_safesearch(_scores(racy="VERY_LIKELY"), **DEFAULTS)
    assert r.allowed is True and r.status == "pass"


def test_scores_echoed_into_result():
    s = _scores(adult="VERY_LIKELY")
    r = evaluate_safesearch(s, **DEFAULTS)
    assert r.scores == s
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && pytest tests/test_photo_moderation_unit.py -v`
Expected: FAIL with `ModuleNotFoundError: app.services.photo_moderation_service`.

- [ ] **Step 3: Write the module (decision core + config)**

```python
# app/services/photo_moderation_service.py
"""Profile-photo NSFW moderation.

Mirrors the stable-interface convention of chat_message_filter.py, but returns
an allow/block DECISION (ModerationResult) rather than mask-in-place. The image
is scanned by Google Cloud Vision SafeSearch; Vision fetches the image from the
client-supplied Firebase Storage URL itself, so the backend never holds bytes.

Decision policy: block if adult >= LIKELY OR violence >= LIKELY; racy is always
allowed (dating photos routinely rate racy). Thresholds are env-tunable.
"""
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Google Vision Likelihood enum values (vision.Likelihood), name -> int.
LIKELIHOOD: dict[str, int] = {
    "UNKNOWN": 0, "VERY_UNLIKELY": 1, "UNLIKELY": 2,
    "POSSIBLE": 3, "LIKELY": 4, "VERY_LIKELY": 5,
}

PHOTO_SCAN_ENABLED: bool = os.getenv("PHOTO_SCAN_ENABLED", "true").lower() == "true"
ADULT_THRESHOLD: int = LIKELIHOOD.get(
    os.getenv("PHOTO_SCAN_ADULT_THRESHOLD", "LIKELY").upper(), LIKELIHOOD["LIKELY"]
)
VIOLENCE_THRESHOLD: int = LIKELIHOOD.get(
    os.getenv("PHOTO_SCAN_VIOLENCE_THRESHOLD", "LIKELY").upper(), LIKELIHOOD["LIKELY"]
)

_BLOCK_REASON = "This photo can't be used. Please choose a different one."


@dataclass
class ModerationResult:
    allowed: bool
    status: str            # "pass" | "block" | "error"
    reason: str | None     # user-facing message when blocked
    scores: dict           # axis -> likelihood int, for the audit log


def evaluate_safesearch(
    scores: dict[str, int], *, adult_threshold: int, violence_threshold: int
) -> ModerationResult:
    """Pure decision: scores dict (axis -> Likelihood int) -> ModerationResult."""
    adult = scores.get("adult", 0)
    violence = scores.get("violence", 0)
    if adult >= adult_threshold or violence >= violence_threshold:
        return ModerationResult(False, "block", _BLOCK_REASON, scores)
    return ModerationResult(True, "pass", None, scores)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_photo_moderation_unit.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/photo_moderation_service.py tests/test_photo_moderation_unit.py
git commit -m "feat(moderation): photo safesearch decision core + config"
```

---

### Task 2: Vision wrapper `scan_image_url` (retry, fail-open, kill-switch, SSRF guard)

Wrap Google Vision: build a client from the existing Firebase service-account credentials, call SafeSearch with `image_uri`, map the annotation to a scores dict, run `evaluate_safesearch`. Handle the kill-switch, an SSRF host allowlist, retry-once, and fail-open. Vision is **lazily imported** inside the function so the module loads even before the dependency is installed and so unit tests can monkeypatch.

**Files:**
- Modify: `app/services/photo_moderation_service.py`
- Modify: `requirements.txt`
- Test: `tests/test_photo_moderation_unit.py` (append)

**Interfaces:**
- Consumes: `evaluate_safesearch`, `ModerationResult`, `LIKELIHOOD`, `PHOTO_SCAN_ENABLED`, `ADULT_THRESHOLD`, `VIOLENCE_THRESHOLD` (Task 1).
- Produces:
  - `async def scan_image_url(url: str) -> ModerationResult`
  - `_is_allowed_host(url: str) -> bool` (SSRF allowlist; Firebase/GCS hosts only)
  - `_run_safesearch(url: str) -> dict[str, int]` (the one function unit tests monkeypatch; does the real Vision call)

- [ ] **Step 1: Write the failing tests (append to `tests/test_photo_moderation_unit.py`)**

```python
import asyncio
from app.services import photo_moderation_service as pm


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_disabled_killswitch_passes_without_vision(monkeypatch):
    monkeypatch.setattr(pm, "PHOTO_SCAN_ENABLED", False)
    called = False
    def _boom(url):  # must NOT be called
        nonlocal called; called = True; return {}
    monkeypatch.setattr(pm, "_run_safesearch", _boom)
    r = _run(pm.scan_image_url("https://firebasestorage.googleapis.com/x"))
    assert r.status == "pass" and r.allowed is True and called is False


def test_non_allowlisted_host_fails_open_error(monkeypatch):
    monkeypatch.setattr(pm, "PHOTO_SCAN_ENABLED", True)
    r = _run(pm.scan_image_url("https://evil.example.com/internal"))
    assert r.status == "error" and r.allowed is True


def test_blocked_image(monkeypatch):
    monkeypatch.setattr(pm, "PHOTO_SCAN_ENABLED", True)
    monkeypatch.setattr(pm, "_run_safesearch",
                        lambda url: {"adult": pm.LIKELIHOOD["VERY_LIKELY"], "violence": 0, "racy": 0})
    r = _run(pm.scan_image_url("https://firebasestorage.googleapis.com/v0/b/x/o/p?alt=media&token=t"))
    assert r.status == "block" and r.allowed is False


def test_vision_error_retries_then_fails_open(monkeypatch):
    monkeypatch.setattr(pm, "PHOTO_SCAN_ENABLED", True)
    calls = {"n": 0}
    def _flaky(url):
        calls["n"] += 1
        raise RuntimeError("vision down")
    monkeypatch.setattr(pm, "_run_safesearch", _flaky)
    r = _run(pm.scan_image_url("https://firebasestorage.googleapis.com/v0/b/x/o/p"))
    assert r.status == "error" and r.allowed is True
    assert calls["n"] == 2  # initial try + one retry
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_photo_moderation_unit.py -v -k "killswitch or allowlisted or blocked_image or retries"`
Expected: FAIL with `AttributeError: module ... has no attribute 'scan_image_url'`.

- [ ] **Step 3: Implement the wrapper (append to `photo_moderation_service.py`)**

```python
from urllib.parse import urlparse

# Firebase Storage / GCS download hosts only — prevents handing an arbitrary
# (SSRF) URL to Vision to fetch.
_ALLOWED_HOSTS = {"firebasestorage.googleapis.com", "storage.googleapis.com"}


def _is_allowed_host(url: str) -> bool:
    try:
        p = urlparse(url)
    except (ValueError, TypeError):
        return False
    if p.scheme != "https":
        return False
    host = (p.hostname or "").lower()
    return host in _ALLOWED_HOSTS or host.endswith(".firebasestorage.app")


def _vision_credentials():
    """Reuse the Firebase service account (same GCP project) for Vision auth."""
    import base64
    import json
    from pathlib import Path
    from google.oauth2 import service_account

    b64 = os.getenv("FIREBASE_CREDENTIALS_B64")
    if b64:
        info = json.loads(base64.b64decode(b64))
        return service_account.Credentials.from_service_account_info(info)
    project_root = Path(__file__).parent.parent.parent
    cred_path = os.getenv(
        "FIREBASE_CREDENTIAL_PATH",
        str(project_root / "facedate-6616e-ebf102022977.json"),
    )
    return service_account.Credentials.from_service_account_file(cred_path)


def _run_safesearch(url: str) -> dict[str, int]:
    """Real Vision SafeSearch call. Returns {axis: Likelihood int}.

    Isolated so unit tests can monkeypatch it without importing google-cloud-vision.
    """
    from google.cloud import vision

    client = vision.ImageAnnotatorClient(credentials=_vision_credentials())
    image = vision.Image(source=vision.ImageSource(image_uri=url))
    response = client.safe_search_detection(image=image)
    if response.error.message:
        raise RuntimeError(f"Vision error: {response.error.message}")
    ann = response.safe_search_annotation
    return {
        "adult": int(ann.adult),
        "violence": int(ann.violence),
        "racy": int(ann.racy),
        "medical": int(ann.medical),
        "spoof": int(ann.spoof),
    }


async def scan_image_url(url: str) -> ModerationResult:
    """Scan one image URL. Never raises — returns a ModerationResult.

    status: pass | block | error. On any failure (bad host, Vision down) this
    fails OPEN (allowed=True, status="error") after one retry.
    """
    if not PHOTO_SCAN_ENABLED:
        return ModerationResult(True, "pass", None, {})

    if not _is_allowed_host(url):
        logger.warning("Photo scan skipped — non-allowlisted host: %s", url)
        return ModerationResult(True, "error", None, {})

    import asyncio
    last_exc = None
    for attempt in range(2):  # initial try + one retry
        try:
            scores = await asyncio.to_thread(_run_safesearch, url)
            return evaluate_safesearch(
                scores,
                adult_threshold=ADULT_THRESHOLD,
                violence_threshold=VIOLENCE_THRESHOLD,
            )
        except Exception as exc:  # noqa: BLE001 — fail-open is intentional
            last_exc = exc
            logger.warning("Photo scan attempt %d failed: %s", attempt + 1, exc)

    logger.error("Photo scan failed (fail-open) for %s: %s", url, last_exc, exc_info=last_exc)
    return ModerationResult(True, "error", None, {})
```

Also append the new dependency:

```text
# requirements.txt — add:
google-cloud-vision>=3.7.0
```

- [ ] **Step 4: Install dep + run tests**

Run: `pip install "google-cloud-vision>=3.7.0" && pytest tests/test_photo_moderation_unit.py -v`
Expected: PASS (all unit tests, including the 4 new ones).

- [ ] **Step 5: Commit**

```bash
git add app/services/photo_moderation_service.py tests/test_photo_moderation_unit.py requirements.txt
git commit -m "feat(moderation): vision safesearch wrapper w/ retry, fail-open, SSRF guard"
```

---

### Task 3: `photo_scan_log` audit table (model + migration)

Append-only audit row per scan, mirroring `AgeAttestation`.

**Files:**
- Modify: `app/models.py` (add `PhotoScanLog` after `AgeAttestation`, ~line 116)
- Create: `alembic/versions/<rev>_add_photo_scan_log.py`
- Test: `tests/test_photo_scan_log_model.py`

**Interfaces:**
- Produces: `models.PhotoScanLog` with columns `id, user_id (nullable FK), image_url (String), decision (String(16)), scores (JSON), created_at (timestamptz)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_photo_scan_log_model.py
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
        user_id=None, image_url="https://firebasestorage.googleapis.com/x",
        decision="block", scores={},
    )
    db.add(row)
    await db.flush()
    assert row.id is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_photo_scan_log_model.py -v`
Expected: FAIL with `AttributeError: module 'app.models' has no attribute 'PhotoScanLog'`.

- [ ] **Step 3a: Add the model (`app/models.py`, after the `AgeAttestation` class)**

```python
class PhotoScanLog(Base):
    """Append-only audit trail: one row per profile-photo SafeSearch scan
    (pass | block | error). See docs/superpowers/specs/2026-06-18-nsfw-photo-scan-design.md."""
    __tablename__ = "photo_scan_log"

    id = Column(Integer, primary_key=True)
    # Nullable: a brand-new signup is blocked before the user row gets an id.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    image_url = Column(String, nullable=False)
    decision = Column(String(16), nullable=False)  # 'pass' | 'block' | 'error'
    scores = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
```

Ensure `JSON` is imported at the top of `models.py` (check the existing `from sqlalchemy import ...` line; add `JSON` if absent).

- [ ] **Step 3b: Create the Alembic migration**

First find the current head:

Run: `DATABASE_URL=postgresql://dating_user:securepassword@localhost/dating_app alembic heads`

Then create `alembic/versions/aa11bb22cc33_add_photo_scan_log.py` (set `down_revision` to the head printed above):

```python
"""add photo_scan_log

Revision ID: aa11bb22cc33
Revises: <CURRENT_HEAD>
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa

revision = "aa11bb22cc33"
down_revision = "<CURRENT_HEAD>"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "photo_scan_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("image_url", sa.String(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_photo_scan_log_user_id", "photo_scan_log", ["user_id"])
    op.create_index("ix_photo_scan_log_created_at", "photo_scan_log", ["created_at"])


def downgrade():
    op.drop_index("ix_photo_scan_log_created_at", table_name="photo_scan_log")
    op.drop_index("ix_photo_scan_log_user_id", table_name="photo_scan_log")
    op.drop_table("photo_scan_log")
```

- [ ] **Step 4: Run model test + apply migration to dev DB**

Run: `pytest tests/test_photo_scan_log_model.py -v` → Expected: PASS (2 tests; test DB builds the table from `Base.metadata`).
Run: `DATABASE_URL=postgresql://dating_user:securepassword@localhost/dating_app alembic upgrade head` → Expected: applies the migration with no error.

- [ ] **Step 5: Commit**

```bash
git add app/models.py alembic/versions/aa11bb22cc33_add_photo_scan_log.py tests/test_photo_scan_log_model.py
git commit -m "feat(moderation): photo_scan_log audit table + migration"
```

---

### Task 4: Shared `moderate_and_log_photos` helper + wire into `POST /users/create`

The helper scans each changed URL, writes a `photo_scan_log` row per scan, **commits the log rows**, and raises 422 on the first block. It is called BEFORE any user mutation so committing the log doesn't flush a half-built user.

**Files:**
- Modify: `app/services/photo_moderation_service.py` (add the DB-aware helper)
- Modify: `app/routers/users.py` (`create_user`, ~line 444; import at top)
- Test: `tests/test_photo_scan_create.py`

**Interfaces:**
- Consumes: `scan_image_url`, `ModerationResult` (Tasks 1–2); `models.PhotoScanLog` (Task 3).
- Produces:
  - `async def moderate_and_log_photos(db, user_id: int | None, urls: list[str]) -> None`
    — scans each non-empty URL, writes a log row each, commits, raises `HTTPException(422, detail=<reason>)` on the first block.

- [ ] **Step 1: Write the failing integration tests**

```python
# tests/test_photo_scan_create.py
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
        return ModerationResult(False, "block", "This photo can't be used. Please choose a different one.", {"adult": 5})
    monkeypatch.setattr(pm, "scan_image_url", _block)

    async with _client(db, "uid_block") as c:
        r = await c.post("/users/create", json={
            "firebase_uid": "uid_block", "email": "b@x.com", "profile_image_url": FB,
        })
    assert r.status_code == 422
    # nothing persisted
    user = (await db.execute(select(models.User).where(models.User.firebase_uid == "uid_block"))).scalars().first()
    assert user is None
    # a block log row exists
    log = (await db.execute(select(models.PhotoScanLog).where(models.PhotoScanLog.decision == "block"))).scalars().first()
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
    user = (await db.execute(select(models.User).where(models.User.firebase_uid == "uid_ok"))).scalars().first()
    assert user is not None and user.profile_image_url == FB
    log = (await db.execute(select(models.PhotoScanLog).where(models.PhotoScanLog.decision == "pass"))).scalars().first()
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_photo_scan_create.py -v`
Expected: FAIL — currently no scanning, so `test_create_blocks_explicit_photo` returns 200 and persists the user.

- [ ] **Step 3a: Add the helper (`photo_moderation_service.py`)**

```python
from fastapi import HTTPException


async def moderate_and_log_photos(db, user_id, urls) -> None:
    """Scan each non-empty URL, log every scan, commit the logs, and raise
    HTTPException(422) on the first block. Call BEFORE mutating the user row so
    the commit here doesn't flush a half-built user.

    `db` is an AsyncSession; `urls` a list of (possibly None/empty) strings.
    """
    from app.models import PhotoScanLog

    blocked: ModerationResult | None = None
    for url in urls:
        if not url or not url.strip():
            continue
        result = await scan_image_url(url)
        db.add(PhotoScanLog(
            user_id=user_id, image_url=url,
            decision=result.status, scores=result.scores or {},
        ))
        if not result.allowed and blocked is None:
            blocked = result
    await db.commit()
    if blocked is not None:
        raise HTTPException(status_code=422, detail=blocked.reason)
```

- [ ] **Step 3b: Wire into `create_user` (`app/routers/users.py`)**

Add the import near the other service imports (~line 12):

```python
from app.services.photo_moderation_service import moderate_and_log_photos
```

In `create_user`, right after `user_data = user.to_user_dict()` and before the `if db_user:` branch, scan the incoming photos (note `additional_image_urls` is already a list after `to_user_dict`):

```python
        # NSFW scan BEFORE persisting — blocked photos never reach the DB.
        existing_id = db_user.id if db_user else None
        photo_urls = [user_data.get("profile_image_url")]
        photo_urls += user_data.get("additional_image_urls") or []
        await moderate_and_log_photos(db, existing_id, photo_urls)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_photo_scan_create.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/photo_moderation_service.py app/routers/users.py tests/test_photo_scan_create.py
git commit -m "feat(moderation): scan photos on POST /users/create (hard block 422)"
```

---

### Task 5: Wire into `PUT /users/me/profile` (scan-on-change)

Scan `profileImageURL` only when it differs from the stored value.

**Files:**
- Modify: `app/routers/users.py` (`update_profile`, ~line 114)
- Test: `tests/test_photo_scan_profile.py`

**Interfaces:**
- Consumes: `moderate_and_log_photos` (Task 4).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_photo_scan_profile.py
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
        return ModerationResult(False, "block", "This photo can't be used. Please choose a different one.", {})
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_photo_scan_profile.py -v`
Expected: FAIL — `test_profile_blocks_explicit_new_photo` returns 200 (no scan yet).

- [ ] **Step 3: Wire into `update_profile` (`app/routers/users.py`)**

After the user is fetched and the `if not user:` 404 guard, before the update loop:

```python
    update_data = profile.dict(exclude_unset=True)
    new_photo = update_data.get("profileImageURL")
    if new_photo and new_photo != user.profile_image_url:
        await moderate_and_log_photos(db, user.id, [new_photo])
```

(The existing `for key, value in profile.dict(exclude_unset=True).items():` loop stays as-is.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_photo_scan_profile.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/routers/users.py tests/test_photo_scan_profile.py
git commit -m "feat(moderation): scan changed photo on PUT /users/me/profile"
```

---

### Task 6: iOS — surface the 422 in the photo-upload UI

When the profile/create call returns 422, show the server's message instead of a generic error so the user knows to pick a different photo.

**Files:**
- Modify: the iOS profile-photo upload error path in `../DatingAppProj/DatingApp/Sources/Features/Profile/` (locate the call site that hits `POST /users/create` or `PUT /users/me/profile`; likely `MultiStepProfileCreationView` / `ProfileUpdateView` and their view models).

**Interfaces:**
- Consumes: backend 422 with `{"detail": "This photo can't be used. Please choose a different one."}`.

- [ ] **Step 1: Locate the upload + error handling**

Run: `grep -rn "users/create\|me/profile\|profileImageURL\|statusCode" ../DatingAppProj/DatingApp/Sources/Features/Profile/`
Identify where the HTTP response status is handled after photo upload.

- [ ] **Step 2: Decode the 422 detail and present it**

In the catch/error branch, when the response status is 422, parse the JSON `detail` string and surface it via the existing alert/toast mechanism (the app uses `.toast()` per DesignSystem). Show the `detail` text; fall back to a generic "This photo can't be used — please choose another." if parsing fails.

- [ ] **Step 3: Build to verify it compiles**

Run:
```bash
cd ../DatingAppProj && xcodebuild -project DatingAppProj.xcodeproj -scheme DatingAppProj \
  -destination 'platform=iOS Simulator,name=iPhone 16' build 2>&1 | tail -20
```
Expected: `BUILD SUCCEEDED`.

- [ ] **Step 4: Commit (iOS repo)**

```bash
cd ../DatingAppProj && git add -A && git commit -m "feat: surface NSFW photo rejection (422) in profile upload"
```

(If `DatingAppProj` is a separate repo/branch, branch first per its conventions; do not push without the user's go-ahead.)

---

### Task 7: Config docs, full-suite check, launch tracker

**Files:**
- Modify: `requirements.txt` (already done in Task 2 — verify present)
- Modify: `LAUNCH_READINESS.md` (flip the checkbox)
- Modify (optional): `app/main.py:189` `_validate_required_env_vars` — only if you want to hard-require photo-scan config in prod (not required; the kill-switch defaults on).
- Reference: `docs/superpowers/specs/2026-06-18-nsfw-photo-scan-design.md`

- [ ] **Step 1: Run the full moderation + regression suite**

Run:
```bash
source venv/bin/activate && pytest tests/test_photo_moderation_unit.py tests/test_photo_scan_log_model.py \
  tests/test_photo_scan_create.py tests/test_photo_scan_profile.py tests/test_users_delete.py -q
```
Expected: all PASS.

- [ ] **Step 2: Document the operational prerequisite**

In the spec file's header (or a short note in `README.md`/`SERVER_PROD.md`), record: **"Cloud Vision API must be enabled on GCP project `facedate-6616e` (Console → APIs & Services → enable 'Cloud Vision API') for photo scanning to work; otherwise scans fail-open with `decision=error`."** Also note the env vars: `PHOTO_SCAN_ENABLED`, `PHOTO_SCAN_ADULT_THRESHOLD`, `PHOTO_SCAN_VIOLENCE_THRESHOLD`.

- [ ] **Step 3: Update the launch tracker**

In `LAUNCH_READINESS.md`, flip the "NSFW photo scan on upload" item to `[x]`, add date `2026-06-18` + branch `feature/nsfw-photo-scan`, and add a Changelog line.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt LAUNCH_READINESS.md docs/superpowers/specs/2026-06-18-nsfw-photo-scan-design.md
git commit -m "docs: photo-scan ops note + flip launch-readiness checkbox"
```

---

## Self-Review

**Spec coverage:** Provider/SafeSearch (Tasks 1–2) ✓; hard-block 422 (Tasks 4–5) ✓; decision policy adult/violence block, racy allow (Task 1) ✓; env-tunable thresholds (Task 1) ✓; fail-open-with-flag + retry (Task 2) ✓; kill-switch (Task 2) ✓; `image_uri` no-byte-download (Task 2) ✓; SSRF host guard (Task 2, security section) ✓; scan-on-change (Tasks 4–5) ✓; `photo_scan_log` audit (Task 3) ✓; config + `google-cloud-vision` (Tasks 2, 7) ✓; iOS 422 surface (Task 6) ✓; Vision-API-enable prerequisite (Task 7) ✓; launch tracker (Task 7) ✓; tests unit+integration (every task) ✓.

**Placeholder scan:** Two intentional fill-ins — `<CURRENT_HEAD>` for the Alembic `down_revision` (resolved by the `alembic heads` command in Task 3 Step 3b) and the iOS file path in Task 6 (resolved by the grep in Step 1, since the exact view-model call site must be located live). All code steps contain real code.

**Type consistency:** `ModerationResult(allowed, status, reason, scores)` and `scan_image_url`/`evaluate_safesearch`/`moderate_and_log_photos` signatures are identical across Tasks 1, 2, 4, 5. `PhotoScanLog` columns match between the model (Task 3), migration (Task 3), and test assertions (Tasks 3–4). `_run_safesearch` is the single monkeypatch seam used consistently in Task 2 tests.
