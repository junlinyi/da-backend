# NSFW Photo Scan on Upload — Design

**Date:** 2026-06-18
**Branch:** `feature/nsfw-photo-scan`
**Status:** Approved design, pending implementation plan
**Launch tracker:** Phase A submission blocker in `LAUNCH_READINESS.md` ("NSFW photo scan on upload")

## Problem

The app has no proactive scanning of user-uploaded photos. `app/services/chat_message_filter.py`
is a 23-line text-only stub. Apple Guideline 1.2 (user-generated content) requires a method to
filter objectionable content — proactive photo scanning is the missing leg (report categories and
user blocking already exist). Absent photo moderation is the single most common dating-app App
Review rejection.

## Key constraint (load-bearing)

**The backend never receives image bytes.** The iOS client uploads photos directly to Firebase
Storage and sends only the resulting HTTPS download URL to the backend, persisted as
`users.profile_image_url` (String) and `users.additional_image_urls` (ARRAY(String)). The only
existing "processing" is `validate_profile_image_url()` in `app/utils.py:261`, a regex
format check. There is **no upload-interception point** — a server-side scan must inspect the image
referenced by the client-supplied URL.

## Goals

- Every newly-set profile photo (primary + additional) is scanned for explicit/violent content
  before it is persisted.
- A photo that fails the scan is **hard-blocked**: the profile save is rejected (HTTP 422) and
  nothing is persisted.
- A durable audit trail records every scan decision (App Review defensibility).
- Lean footprint: reuse the existing Firebase/GCP service account; one new Python dependency.

## Non-Goals

- Scanning chat messages for images (chat is text-only today; out of scope).
- On-device (iOS) scanning. Apple's `SensitiveContentAnalysis` as a UX pre-filter is a possible
  future nicety, explicitly out of scope here. Client-side scanning is bypassable and cannot be the
  enforcement authority.
- Re-scanning already-stored photos (a backfill job could be added later; not required for launch).
- Face-similarity / photo-verification (separate roadmap item in `PRODUCTION_GAPS.md`).

## Design Decisions

### Provider: Google Cloud Vision SafeSearch
The Firebase service account (`facedate-6616e`) is already a GCP service account in the **same
project**, so SafeSearch needs no new vendor, billing relationship, or credentials — only the Vision
API enabled and the `google-cloud-vision` package. ~$1.50/1k images, sub-second, recognized by App
Review. (AWS Rekognition — the `PRODUCTION_GAPS.md` note — was rejected here: it needs new IAM creds
+ `boto3`. Sightengine/Hive rejected: third-party vendor + new account.)

Vision is invoked with `ImageSource.image_uri` set to the Firebase Storage download URL — Vision
fetches the image itself (Firebase download URLs are token-public), so **the backend never downloads
bytes** and needs no HTTP client dependency.

### Enforcement: hard synchronous block
On profile-photo write, the scan runs synchronously and a failing photo causes the whole save to be
rejected (422) before persistence. Profile saves are infrequent, so the ~1s added latency is
acceptable, and "objectionable photo never goes live" is the strongest App Review posture.

### Decision policy (env-tunable)
SafeSearch returns a likelihood per axis: `UNKNOWN`, `VERY_UNLIKELY`, `UNLIKELY`, `POSSIBLE`,
`LIKELY`, `VERY_LIKELY`.

- **Block** if `adult >= LIKELY` **or** `violence >= LIKELY`.
- **Allow** `racy` at any level. This is the swimwear/beach case — dating photos routinely rate
  "racy", and blocking it would reject legitimate users.
- Thresholds configurable via env (`PHOTO_SCAN_ADULT_THRESHOLD`, `PHOTO_SCAN_VIOLENCE_THRESHOLD`)
  so strictness can change without a deploy.

### Failure mode: fail-open with flag
If Vision is unreachable or the fetch fails: **retry once, then fail-open** (allow the save), record
`decision = "error"` in the audit log, and report to Sentry. Rationale: a GCP blip must not block
every user's profile save; the audit trail enables a later re-scan. (Fail-closed was considered —
safest for App Review but risks blocking legitimate users during an outage.)

### Scan-on-change only
A photo is scanned only when its URL actually differs from what is stored, so ordinary profile edits
(bio, preferences) don't re-scan unchanged photos or add latency.

## Components

### `app/services/photo_moderation_service.py` (new)
Mirrors the "stable public interface" convention of `chat_message_filter.py`, but returns an
allow/block decision rather than mask-in-place.

```python
@dataclass
class ModerationResult:
    allowed: bool
    status: str            # "pass" | "block" | "error"
    reason: str | None     # user-facing message when blocked
    scores: dict           # axis -> likelihood string, for the audit log

async def scan_image_url(url: str) -> ModerationResult: ...
```

Responsibilities: build the Vision client (lazily, from Firebase credentials), call SafeSearch with
`image_uri`, map likelihoods to a decision via the env thresholds, handle retry/fail-open. Pure
decision logic (likelihood-dict → `ModerationResult`) is factored into a separate sync helper so it
can be unit-tested without the Vision client.

Kill-switch: when `PHOTO_SCAN_ENABLED` is false, `scan_image_url` returns an immediate
`status="pass"` (no Vision call) — lets the feature be disabled in dev/staging.

### `app/routers/users.py` (modified)
- `POST /users/create`: scan `profile_image_url` and each `additional_image_urls` entry. On any
  block, raise 422 identifying which photo failed; persist nothing.
- `PUT /users/me/profile`: scan `profileImageURL` only when it differs from the stored value.
- Each scan result is written to the audit log (see below) regardless of outcome.

A small shared helper (e.g. `_moderate_photos(urls) -> None | raises HTTPException`) keeps both
endpoints DRY.

### `photo_scan_log` table (new, via Alembic) — audit trail
Mirrors the `age_attestations` audit pattern.

| column      | type        | notes                                   |
|-------------|-------------|-----------------------------------------|
| id          | int PK      |                                         |
| user_id     | int FK      | nullable for create-before-user-id case |
| image_url   | String      | the scanned URL                         |
| decision    | String      | "pass" \| "block" \| "error"            |
| scores      | JSON        | axis -> likelihood                      |
| created_at  | timestamptz | `datetime.now(timezone.utc)`            |

No per-image status column on `users` is needed: hard-block means only passing photos persist.

### Config (`.env` + `os.getenv`, no Settings class)
- `PHOTO_SCAN_ENABLED` (default true in prod, overridable) — kill-switch.
- `PHOTO_SCAN_ADULT_THRESHOLD` (default `LIKELY`), `PHOTO_SCAN_VIOLENCE_THRESHOLD` (default `LIKELY`).
- Vision auth reuses the existing `FIREBASE_CREDENTIAL_PATH` / `FIREBASE_CREDENTIALS_B64`.
- Add `google-cloud-vision` to `requirements.txt`.
- Optionally extend `_validate_required_env_vars` (`app/main.py:189`).

### iOS (`DatingAppProj`, minimal)
Surface the 422 rejection gracefully in the photo-upload UI ("This photo can't be used — please
choose another"). No client-side scanning. Identify the exact upload/error path during planning.

## Data Flow

```
iOS uploads photo → Firebase Storage → iOS sends URL to backend
  POST /users/create  or  PUT /users/me/profile
    └─ _moderate_photos([urls])
         └─ scan_image_url(url)  [per changed URL]
              └─ Vision SafeSearch (image_uri = url)
                   ├─ pass  → log "pass",  continue
                   ├─ block → log "block", raise 422 (nothing persisted)
                   └─ error → retry once → fail-open, log "error", Sentry
    └─ persist user/profile (only clean URLs ever reach here)
```

## Error Handling

| Condition                        | Behavior                                               |
|----------------------------------|--------------------------------------------------------|
| Photo fails SafeSearch           | 422, message names the failing photo, nothing persisted|
| Vision unreachable / fetch fails | retry once → fail-open, log "error", Sentry            |
| `PHOTO_SCAN_ENABLED=false`       | immediate pass, no Vision call                          |
| Malformed/non-HTTP URL           | existing `validate_profile_image_url` rejects first     |

## Test Plan (TDD)

**Unit** (`tests/`, Vision client mocked) — decision helper against fixture SafeSearch responses:
- `adult=LIKELY` → block; `adult=VERY_LIKELY` → block; `adult=POSSIBLE` → allow.
- `racy=VERY_LIKELY` (with low adult) → allow (the swimwear case).
- `violence=LIKELY` → block.
- threshold boundary exactly at configured level.
- Vision raises → after one retry, fail-open (`status="error"`, allowed=True).
- `PHOTO_SCAN_ENABLED=false` → pass without calling Vision.

**Integration** (endpoints, scanner mocked — no real NSFW fixtures needed):
- `POST /users/create` with a flagged URL → 422, no user row, a `block` log row.
- `PUT /users/me/profile` with a flagged URL → 422, profile unchanged.
- clean URL → 200, user persisted, a `pass` log row.
- unchanged URL on profile edit → scanner not called.

## Security Review

- No image bytes touch the backend; Vision fetches via token-public Firebase URL.
- Service-account credentials already present; no new secret store.
- Audit log retains image URLs + decisions — acceptable (URLs already stored on `users`); contains
  no new PII beyond what exists.
- SSRF consideration: `scan_image_url` should accept only `https://` Firebase Storage hosts (reuse
  `validate_profile_image_url` + a host allowlist) so the URL passed to Vision can't be pointed at
  internal resources.

## Success Metrics

- 100% of newly-set profile photos produce a `photo_scan_log` row.
- Explicit test images are rejected with 422; clean images pass.
- App Review: photo-moderation requirement satisfied (Phase A blocker cleared).

## Deprecation Checklist

None — this is net-new. `chat_message_filter.py` is untouched (separate text-moderation concern).

## Implementation Checklist (high-level — detailed plan follows via writing-plans)

1. `photo_moderation_service.py` + pure decision helper.
2. Unit tests for decision/failure logic.
3. Alembic migration for `photo_scan_log` + ORM model.
4. Wire `_moderate_photos` into `POST /users/create` and `PUT /users/me/profile`.
5. Integration tests for both endpoints.
6. Config + `requirements.txt` (`google-cloud-vision`); enable Vision API on the GCP project.
7. iOS: surface 422 in photo-upload UI.
8. Update `LAUNCH_READINESS.md` (flip the checkbox, add date + branch).
