"""Profile-photo NSFW moderation.

Mirrors the stable-interface convention of chat_message_filter.py, but returns
an allow/block DECISION (ModerationResult) rather than mask-in-place. The image
is scanned by Google Cloud Vision SafeSearch; Vision fetches the image from the
client-supplied Firebase Storage URL itself, so the backend never holds bytes.

Decision policy: block if adult >= LIKELY OR violence >= LIKELY; racy is always
allowed (dating photos routinely rate racy). Thresholds are env-tunable.

See docs/superpowers/specs/2026-06-18-nsfw-photo-scan-design.md.
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


# Firebase Storage / GCS download hosts only — prevents handing an arbitrary
# (SSRF) URL to Vision to fetch.
_ALLOWED_HOSTS = {"firebasestorage.googleapis.com", "storage.googleapis.com"}


def _is_allowed_host(url: str) -> bool:
    from urllib.parse import urlparse
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


async def moderate_and_log_photos(db, user_id, urls) -> None:
    """Scan each non-empty URL, log every scan, commit the logs, and raise
    HTTPException(422) on the first block. Call BEFORE mutating the user row so
    the commit here doesn't flush a half-built user.

    `db` is an AsyncSession; `urls` a list of (possibly None/empty) strings.
    """
    from fastapi import HTTPException
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
