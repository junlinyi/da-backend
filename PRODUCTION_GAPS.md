# Production Gaps — Dating App

**Last updated:** 2026-04-17  
**Scope:** Full stack — FastAPI backend (`da-backend/`) + iOS frontend (`DatingAppProj/`)  
**Excludes:** Push notifications (tracked separately)

Severity legend:
- **P0** — Launch blocker. Ship nothing until resolved.
- **P1** — Broken feature. Real users will hit this immediately.
- **P2** — Poor UX or data quality issue. Can ship, but creates churn or debt.
- **P3** — Nice-to-have. Post-launch.

---

## Summary

| Category | P0 | P1 | P2 | P3 | Total |
|---|---|---|---|---|---|
| Security | 2 | 3 | 3 | 0 | **8** |
| Backend completeness | 0 | 6 | 6 | 0 | **12** |
| iOS completeness | 1 | 4 | 6 | 0 | **11** |
| Data model / database | 0 | 3 | 4 | 0 | **7** |
| Video call flow | 0 | 2 | 2 | 1 | **5** |
| Scheduling flow | 0 | 2 | 2 | 0 | **4** |
| Safety / moderation | 0 | 3 | 2 | 0 | **5** |
| Onboarding | 0 | 2 | 2 | 1 | **5** |
| Infrastructure | 1 | 1 | 4 | 1 | **7** |
| **TOTAL** | **4** | **26** | **31** | **3** | **64** |

---

## P0 — Launch Blockers

These must be resolved before any real user touches the app.

### SEC-01 · TEST_MODE auth backdoor
**File:** `app/dependencies.py:25`  
If the `TEST_MODE=true` environment variable is set, any request with a token prefixed `test_` completely bypasses Firebase token verification. If this env var is accidentally set in production (e.g. copied from a dev `.env`), the entire auth layer is gone.  
**Fix:** Delete the TEST_MODE branch entirely. Use a separate Firebase project with real credentials for integration tests instead.

### SEC-02 · No HTTPS anywhere
**Files:** `app/main.py`, `DatingApp/Sources/Utils/APIConfig.swift`  
All traffic uses plain HTTP — including Firebase auth tokens, user profile data, and Twilio credentials. iOS hardcodes `http://192.168.1.120:8000`. Auth tokens are exposed on any shared network.  
**Fix:** Deploy behind a TLS-terminating reverse proxy (nginx + Let's Encrypt or AWS ALB). Update `APIConfig.swift` to use `https://` production URL. Add ATS exception removal from iOS `Info.plist` for localhost only.

### IOS-01 · Hardcoded fallback user ID 75
**File:** `DatingApp/Sources/Features/Auth/AuthViewModel.swift` (fetchBackendUserId fallback)  
If `fetchBackendUserId()` fails (network error, 404, etc.), the app silently falls back to backend user ID 75 (a seeded test user). Every swipe, match, and call from a real user who hits this error is attributed to user 75.  
**Fix:** Remove the fallback entirely. On failure, show an error alert and block navigation until the ID is confirmed. Never proceed with a hardcoded ID.

### INFRA-01 · Secrets in source-adjacent files
**File:** `da-backend/.env`  
Twilio Account SID, Auth Token, and Firebase credential file path are stored in `.env`. Even if `.gitignore` is correct, secrets are visible in shell history, CI logs, and any accidental commit. Firebase service account JSON is on disk with no access restrictions.  
**Fix:** Before production, rotate all Twilio keys. Store secrets in a secrets manager (AWS Secrets Manager, GCP Secret Manager, or Doppler). Load at runtime, never from a committed file. Restrict Firebase service account JSON permissions to minimum required scopes.

---

## Security

### SEC-03 · CORS defaults to wildcard · P1
**File:** `app/main.py:48–58`  
If `ALLOWED_ORIGINS` environment variable is unset (the default), CORS allows `*`. Any website can make authenticated requests to the API on behalf of a logged-in user.  
**Fix:** Require `ALLOWED_ORIGINS` to be explicitly set; raise a startup error if missing in production mode. Never default to `*`.

### SEC-04 · No rate limiting on auth or swipe endpoints · P1
**Files:** `app/routers/auth.py`, `app/routers/matchmaking.py`  
Register, sign-in, and swipe endpoints have no rate limiting. Auth endpoints are vulnerable to credential stuffing; swipe endpoint can be spammed thousands of times per second to pollute the behavioral event log.  
**Fix:** Add `slowapi` middleware. Auth: 5 requests/minute per IP. Swipe: 1 request/500ms per authenticated user.

### SEC-05 · Missing auth ownership check on user_id path params · P1
**File:** `app/routers/matchmaking.py:122–129`  
Several endpoints accept `user_id` as a path parameter and query data for that user without verifying the authenticated caller owns that ID. Andrew can query Lena's match list.  
**Fix:** In every endpoint with a `user_id` path param, resolve the caller's backend ID from `decoded_token["uid"]` and assert it matches the path param. Return 403 if not.

### SEC-06 · No input length limits on `bio` and `name` · P2
**File:** `app/schemas.py` (ProfileUpdate model)  
`bio` and `name` fields have no `max_length` constraint. A user can store megabytes of text, causing DB bloat and potential DoS via large response payloads.  
**Fix:** Add `Field(max_length=500)` to `bio`, `Field(max_length=100)` to `name` in all relevant Pydantic schemas.

### SEC-07 · Profile image URL not validated · P2
**File:** `app/schemas.py` (ProfileUpdate.profileImageURL)  
Accepts any string. No check that it's a valid URL or reachable image. Users can store arbitrary strings or internal network addresses.  
**Fix:** Use Pydantic `HttpUrl` type or a regex validator that requires `https://` prefix.

### SEC-08 · `datetime.utcnow()` usage (deprecated) · P2
**Files:** Various routers and services  
`datetime.utcnow()` is deprecated since Python 3.12 and returns a naive datetime (no timezone info), which can cause silent comparison bugs with timezone-aware DB timestamps.  
**Fix:** Replace all `datetime.utcnow()` with `datetime.now(timezone.utc)`. Grep: `git grep -n "utcnow()"`.

---

## Backend Completeness

### BE-01 · No call rating endpoint · P1
**Files:** `app/models.py` (CallRating model exists), `app/routers/video_calls.py` (no rating route)  
The `CallRating` model and table exist in the database, but there is no API endpoint to submit a rating. iOS cannot complete the post-call rating flow. The ML matchmaking system's `avg_call_rating` feature will always be null.  
**Fix:** Add `POST /video-calls/{call_id}/rate` accepting `{"rating": int, "notes": str}`. Write to `call_ratings` table. Update `MatchOutcome.avg_call_rating`.

### BE-02 · No call end / outcome recording · P1
**File:** `app/routers/video_calls.py`  
When a Twilio room closes (participants disconnect), nothing records the outcome. Calls stay in `"scheduled"` or `"in_progress"` state forever. There is no `completed_at`, no `actual_duration`, no no-show flag.  
**Fix:** Add `POST /video-calls/{call_id}/end` endpoint. Accept `{"actual_duration_minutes": int, "ended_reason": str}`. Update `ScheduledCall.status`, `completed_at`, `actual_duration_minutes`. Trigger feature vector recompute for both users.

### BE-03 · 48-hour match expiry not enforced · P1
**File:** `app/routers/matchmaking.py`, `app/routers/scheduling.py`  
The app's core thesis is urgency — matches expire after 48 hours to encourage prompt connection. This logic does not exist. Matches never expire. The `expires_at` field exists in the schema but is never checked.  
**Fix:** Add a background job (APScheduler or Celery beat) that runs every 15 minutes: mark matches as `status="expired"` where `matched_at + 48h < now` and no call is scheduled. Filter expired matches from discovery and scheduling views.

### BE-04 · Block endpoint incomplete · P1
**File:** `app/routers/users.py:193–210`  
The block endpoint writes to the `reports` table but does not: (1) mark the match as `status="blocked"`, (2) archive the Firestore conversation, (3) exclude the blocked user from future discovery results. The blocked user can still see the blocker in the swipe stack.  
**Fix:** In the block endpoint: set `Match.status = "blocked"` for any match between the two users; call Firestore to set `conversation.archived = true`; ensure `find_matches_ml()` excludes blocked users in both directions.

### BE-05 · Block not bidirectional in matchmaking filter · P1
**File:** `app/services/ml_matchmaking.py` (find_matches_ml exclusion logic)  
The exclusion set in `find_matches_ml()` only excludes users the current user has reported. It does not exclude users who have blocked the current user, meaning a blocked user can still see the blocker in their swipe stack.  
**Fix:** Query in both directions: `WHERE reporter_id = me OR reported_user_id = me` when building `blocked_ids`.

### BE-06 · `match_outcomes` table never written to · P1
**File:** `app/routers/matchmaking.py` (match creation), `app/services/ml_matchmaking.py`  
`MatchOutcome` rows are created when a match forms, but `first_message_at`, `reciprocal_msg_at`, `call_completed_at`, and `avg_call_rating` are never populated. The ML feature service reads these columns to compute `message_rate`, `call_rate`, and `response_rate` — all will be null indefinitely.  
**Fix:** Hook into: (1) first message send → update `first_message_at`; (2) first reply → update `reciprocal_msg_at`; (3) call end → update `call_completed_at`; (4) call rating submit → update `avg_call_rating`.

### BE-07 · No rollback when swipe + feature vector fail together · P2
**File:** `app/routers/matchmaking.py:77–80`  
The swipe is committed to the DB even if the feature vector recompute raises an exception (the `try/except` swallows all errors). If the DB is under pressure and the feature recompute fails repeatedly, the feature vectors fall behind actual behavior.  
**Fix:** Wrap swipe insert and feature recompute in a single transaction. If recompute fails, still commit the swipe but log a warning and enqueue an async retry.

### BE-08 · Expired proposals never cleaned up · P2
**File:** `app/routers/scheduling.py`  
`SchedulingProposal` rows with `status="pending"` and `expires_at` in the past are never marked as expired. They continue to appear in "pending proposals" queries.  
**Fix:** Add a background job (runs hourly): `UPDATE scheduling_proposals SET status='expired' WHERE status='pending' AND expires_at < now()`.

### BE-09 · No conflict re-check on proposal accept · P2
**File:** `app/routers/scheduling.py` (proposal accept endpoint)  
When a user accepts a scheduling proposal, the endpoint does not re-verify that the proposed time slot is still available. If the receiver updated their availability between proposal send and accept, a double-booking occurs.  
**Fix:** Re-run `check_scheduling_conflict()` inside the accept endpoint. Return 409 if the slot is now taken; return a helpful message suggesting they pick a new time.

### BE-10 · Twilio call token hardcoded to 1-hour expiry · P2
**File:** `app/routers/video_calls.py:72`  
Token TTL is hardcoded to 3600 seconds (1 hour). Any call lasting over an hour will fail mid-stream when the token expires and Twilio rejects media operations.  
**Fix:** Set TTL to `max(call_duration_minutes * 60 * 1.5, 3600)` so the token always outlasts the scheduled call.

### BE-11 · `datetime.utcnow()` in scheduling validators · P2
**File:** `app/schemas.py` scheduling validators  
Naive datetimes compared against timezone-aware DB timestamps produce silent wrong results (Python does not raise, it just compares incorrectly).  
**Fix:** As noted in SEC-08 — global replacement of `utcnow()` with `now(timezone.utc)`.

### BE-12 · Print statements in production routers · P2
**Files:** `app/routers/matchmaking.py` (many `print("[SWIPE_DEBUG]"...)` calls)  
Debug print statements flush to stdout in production, are not indexable by log aggregators, and mix with structured log output. In high-traffic scenarios they become a performance bottleneck.  
**Fix:** Replace all `print(...)` in router files with `logger.debug(...)` or `logger.info(...)`. Configure logging once in `main.py`.

---

## iOS Completeness

### IOS-02 · Silent failure on swipe sync · P1
**File:** `DatingApp/Sources/Features/Discovery/SwipeViewModel.swift` (`syncSwipeToBackend`)  
If the swipe API call fails (timeout, 5xx, network loss), the failure is only printed to the console. The user sees no error and believes their swipe was recorded. On the next app launch the swipe is lost — the user re-sees a card they already acted on.  
**Fix:** On sync failure, show a non-blocking toast: "Couldn't sync — will retry". Implement exponential backoff retry (3 attempts, 1s/2s/4s). If all retries fail, restore the card to the top of the stack.

### IOS-03 · Auth backend ID fetch failure is silent · P1
**File:** `DatingApp/Sources/Features/Auth/AuthViewModel.swift` (`fetchBackendUserId`)  
If the backend call to resolve `firebase_uid → backend_id` fails, the error is printed to console and the app proceeds as if nothing happened (with the fallback ID, per P0 IOS-01). Once the P0 is fixed, this needs a visible error state.  
**Fix:** Show an alert: "Couldn't connect to server. Please check your connection and try again." with a Retry button. Block tab navigation until the ID is resolved.

### IOS-04 · Counter-proposal button is a no-op · P1
**File:** `DatingApp/Sources/Features/Scheduling/ProposalResponseView.swift`  
The "Counter Propose" button exists in the UI with an empty action closure `{ }`. Tapping it does nothing.  
**Fix:** Implement counter-proposal: present a time-picker sheet, construct a new `SchedulingProposal`, POST to `/scheduling/proposals`. Dismiss the original proposal on success.

### IOS-05 · Timezone not applied in scheduling UI · P1
**Files:** `DatingApp/Sources/Features/Scheduling/SchedulingView.swift`, `When2MeetView.swift`  
All times are displayed in UTC. A user in New York sees "9:00 PM" when the call is at 9 PM UTC (5 PM their time). Users will join calls at the wrong hour.  
**Fix:** Store the user's `TimeZone` (from `TimeZone.current`) and apply `TimeZone` conversion when rendering any `Date` in scheduling views. Send all times as UTC ISO-8601 to the backend (already correct); only convert on display.

### IOS-06 · No spinner during Twilio connect · P2
**File:** `DatingApp/Sources/Features/VideoCall/VideoCallView.swift:63–72`  
`isLoading` state exists in the view but is never toggled. During Twilio token fetch and room join, the user sees a blank or partially-rendered screen with no indication that anything is happening.  
**Fix:** Set `isLoading = true` before token fetch begins; `isLoading = false` when `connectionStatus` reaches `.connected` or on error. Overlay a `ProgressView` + "Connecting…" label.

### IOS-07 · No image caching on swipe cards · P2
**Files:** `DatingApp/Sources/Features/Discovery/SwipeView.swift`, all `AsyncImage` usages  
`AsyncImage` fetches the full-resolution image from the URL on every render. Swiping through 10 profiles re-downloads up to 10 images. On a slow connection, cards appear blank for seconds.  
**Fix:** Use `URLCache` with a 50MB disk cache, or integrate Kingfisher (`KFImage`). Pre-fetch the next 2 cards' images while the current card is displayed.

### IOS-08 · Unread badge never clears · P2
**File:** `DatingApp/Sources/Features/Messages/MessagesView.swift`  
The unread message count badge on the Messages tab increments when new messages arrive (via Firestore listener) but is never decremented when the user reads those messages. The badge sticks indefinitely.  
**Fix:** When a conversation is opened (`ChatView.onAppear`), call a "mark read" function: update the Firestore conversation doc (`unread_count = 0` for the current user's field); update local state on `MessagesViewModel`.

### IOS-09 · Hardcoded backend IP in ChatViewModel · P2
**File:** `DatingApp/Sources/Features/Messages/ChatViewModel.swift` (URL construction)  
A URL is constructed with the literal string `http://192.168.1.120:8000/messaging/...` instead of going through `APIConfig.buildURL(for:)`. This will silently fail when deployed to any environment other than the developer's home WiFi.  
**Fix:** Replace with `APIConfig.buildURL(for: "/messaging/conversations/\(conversationId)/messages")`.

### IOS-10 · No retry on Twilio connection failure · P2
**File:** `DatingApp/Sources/Features/VideoCall/VideoCallManager.swift`  
A transient network error during room join immediately presents a failure state with no retry option. Users on mobile networks (brief LTE drops) cannot recover without killing and re-launching the app.  
**Fix:** On join failure, automatically retry up to 3 times with 2s backoff before showing the error state. Show a "Reconnecting (1/3)…" label during retries.

### IOS-11 · Empty states lack guidance · P2
**File:** `DatingApp/Sources/Features/Scheduling/SchedulingView.swift`  
When a new user has no matches, no proposals, and no calls, all sections of the scheduling view are simultaneously empty. The screen shows four consecutive "nothing here" states with no actionable guidance.  
**Fix:** Replace with a single contextual empty state: if the user has no matches yet, show "Go like someone!" with a button that switches to the Discover tab. If they have matches but no proposals, show "Send \(name) a time to meet!".

### IOS-12 · Retain cycle risk in VideoCallManager · P2
**File:** `DatingApp/Sources/Features/VideoCall/VideoCallManager.swift`  
Participant observer closures capture `self` without `[weak self]`. If the user ends the call while a Twilio callback is in flight, the manager is held alive by the closure after the view is dismissed.  
**Fix:** Audit all closure captures in `VideoCallManager`; add `[weak self]` and `guard let self = self else { return }` to every closure that closes over `self`.

---

## Data Model / Database

### DB-01 · Orphan rows on user deletion · P1
**File:** `app/routers/users.py:179–191` (delete account endpoint), `app/models.py`  
Deleting a user cascades correctly for some relations but not all. `ScheduledCall.user1_id`, `ScheduledCall.user2_id`, `SchedulingProposal.proposer_id`, `BehavioralEvent.user_id` do not have `ondelete="CASCADE"` on their foreign keys. Deleting a user leaves orphan rows across multiple tables.  
**Fix:** Add `ondelete="CASCADE"` to all `ForeignKey` declarations that reference `users.id`. Create an Alembic migration for the constraint changes.

### DB-02 · No soft delete / GDPR compliance · P1
**File:** All models  
All deletes are hard deletes. GDPR Article 17 ("right to erasure") requires the ability to prove deletion occurred and to honor deletion requests within 30 days. Hard-deleting also makes it impossible to recover from accidental account removal.  
**Fix:** Add `deleted_at: DateTime` nullable column to `User` (and `Match`, `Conversation`). Filter `WHERE deleted_at IS NULL` everywhere. Schedule hard deletion 30 days after `deleted_at` is set. Log deletion events to an immutable audit table.

### DB-03 · Profile completion not used as a gate · P1
**File:** `app/models.py:33` (`profile_completed` boolean), `app/services/ml_matchmaking.py` (find_matches_ml)  
The `profile_completed` boolean is set but never checked in matchmaking queries. Users who skipped onboarding (no photo, no age, no bio) appear in the swipe stack.  
**Fix:** Add `User.profile_completed == True` to the hard filter in `find_matches_ml()`. Add a profile completion check in `GET /matchmaking/potential-matches` that returns a 403 with a `"profile_incomplete"` error code if the caller's profile isn't complete.

### DB-04 · No migration system for ML schema · P2
**Files:** `add_ml_schema.sql`, `add_scheduling_constraints.sql`, `update_common_availability_function.sql`  
All recent schema changes were applied via raw `.sql` files manually run against the database. Alembic exists in the repo but these changes are not in it. A fresh environment setup has no documented, reproducible order for applying these scripts.  
**Fix:** Create Alembic migrations for: `user_values`, `user_feature_vectors`, `behavioral_events`, `match_outcomes` tables; the `check_scheduling_conflict` SQL function; all indexes added by `add_ml_schema.sql`. Make `alembic upgrade head` the single deploy step.

### DB-05 · Missing indexes on hot query paths · P2
**File:** `app/models.py`  
Columns queried on every matchmaking request and every scheduling lookup have no explicit indexes:
- `matches.user1_id`, `matches.user2_id`, `matches.status`
- `scheduled_calls.user1_id`, `scheduled_calls.user2_id`, `scheduled_calls.status`
- `user_default_availability.user_id`
- `swipes.swiped_id` (checked on every like to detect mutual match)  

**Fix:** Add `Index("idx_matches_user1", Match.user1_id)` etc. in model definitions or in an Alembic migration. Run `EXPLAIN ANALYZE` on the 5 highest-frequency queries to validate.

### DB-06 · Strike system never used · P2
**File:** `app/models.py:35` (`strikes` integer column on User)  
The `strikes` column exists but is never incremented when a report is submitted, and its value is never checked. Repeat-offending users cannot be auto-banned.  
**Fix:** In the report submission endpoint: `UPDATE users SET strikes = strikes + 1 WHERE id = reported_user_id`. Add a trigger (or application-layer check): if `strikes >= 3`, set `is_active = false`. If `strikes >= 5`, set `is_banned = true`.

### DB-07 · No cascade cleanup for Firestore on match delete · P2
**File:** `app/routers/matchmaking.py` (match creation), Firebase integration  
When a match is deleted or blocked in PostgreSQL, the corresponding Firestore conversation document is not archived or deleted. iOS Firestore listeners continue receiving updates for conversations that no longer exist on the backend.  
**Fix:** After any match status change to `"blocked"` or `"expired"`, call the Firebase Admin SDK to set `conversations/{matchId}.archived = true` and `conversations/{matchId}.active = false`.

---

## Video Call Flow

### VC-01 · No no-show detection · P1
**File:** `app/routers/video_calls.py`, background jobs (none exist)  
If one or both users never join a scheduled call, it stays in `"scheduled"` state forever. There is no timeout, no no-show flag, and no notification to the other user. The ML system cannot learn from no-shows.  
**Fix:** Background job runs every 5 minutes: for each call where `start_time + 20min < now` and `status = "scheduled"`, mark it `"no_show"`. Log a `BehavioralEvent(event_type="call_no_show")` for the absent user(s). Optionally notify the waiting user.

### VC-02 · Call duration not tracked · P1
**File:** `app/models.py` (`ScheduledCall.actual_duration_minutes` column exists but is never set)  
The column exists to record how long the call actually lasted (vs. the scheduled duration), but no endpoint sets it. The ML system cannot use call duration as a quality signal.  
**Fix:** Resolved by implementing BE-02 (call end endpoint). Twilio sends a webhook when a room closes with participant duration data; use this to populate `actual_duration_minutes`.

### VC-03 · Twilio room never explicitly closed · P2
**File:** `app/routers/video_calls.py`  
Twilio rooms are created but never explicitly closed via the REST API. Twilio auto-closes rooms after all participants leave, but rooms with connectivity issues can remain open consuming resources and billing.  
**Fix:** In the call end endpoint (BE-02), call `twilio_client.video.rooms(room_name).update(status="completed")` to force-close the room.

### VC-04 · No call recording for moderation · P3
**File:** All video call infrastructure  
There is no mechanism to record calls for abuse investigation. A user can make threats or share illegal content on a call and there is no evidence for moderation review.  
**Fix:** (Post-launch) Enable Twilio Composition recordings for flagged users. Store recording URLs in `scheduled_calls`. Add admin endpoint to access recordings linked to a report.

---

## Scheduling Flow

### SCHED-01 · Scheduling conflict check inconsistent with availability grid · P1
**File:** `add_scheduling_constraints.sql` (`check_scheduling_conflict` function), `update_common_availability_function.sql` (`find_common_availability` function)  
`find_common_availability` uses override-first logic (`COALESCE(override.is_available, default.is_available)`), but `check_scheduling_conflict` does not. The grid shows a slot as available, but attempting to book it returns a 409 conflict.  
**Fix:** Rewrite `check_scheduling_conflict` to use the same `COALESCE(override, default)` logic. The corrected SQL already exists in `add_scheduling_constraints.sql` — apply it: `psql -U dating_user -d dating_app -f add_scheduling_constraints.sql`.

### SCHED-02 · 48-hour expiry not enforced · P1
See BE-03 above. Documented here as it affects the scheduling view directly — expired matches should not appear in "Pick a Time" or "Waiting for Response" sections.  
**Fix:** Same background job as BE-03. Additionally, filter the scheduling view to exclude matches where `expires_at < now`.

### SCHED-03 · No conflict re-check on proposal accept · P2
See BE-09 above.

### SCHED-04 · Empty scheduling view has no guidance · P2
See IOS-11 above.

---

## Safety / Moderation

### SAFE-01 · Report system has no admin review tooling · P1
**File:** `app/routers/admin.py`  
The admin endpoint to list reports exists, but there is no: report detail view (showing the reported user's profile, their messages, their call history), bulk action tooling, ban/warn action endpoint from the admin panel, or feedback to the reporter about the outcome of their report.  
**Fix:** Add `GET /admin/reports/{report_id}` returning full context (reporter, reported user, evidence, prior reports against same user). Add `POST /admin/reports/{report_id}/action` accepting `{"action": "warn|ban|dismiss", "notes": str}`. Trigger a strike increment and optional account suspension on ban action.

### SAFE-02 · Blocked user can still see the blocker · P1
See BE-05 above.

### SAFE-03 · Conversation not archived on block · P1
**File:** `app/routers/users.py` (block endpoint), Firebase integration  
When user A blocks user B, the Firestore conversation between them remains active and unarchived. User A's Messages tab still shows the conversation thread. The block only prevents future matches, not continued access to the existing conversation.  
**Fix:** In the block endpoint, after updating the match status, call Firebase Admin SDK to set `archived = true` on the conversation document. Update the iOS Firestore listener to exclude archived conversations from `MessagesView`.

### SAFE-04 · No strike auto-ban logic · P2
See DB-06 above.

### SAFE-05 · No photo verification / catfish prevention · P2
**File:** `app/models.py:34` (`is_verified` boolean exists but unused)  
`is_verified` is in the schema but no endpoint triggers verification. Users can upload any photo and claim to be anyone.  
**Fix:** Add a verification flow: prompt user to take a selfie matching a pose shown on screen (liveness check). Compare selfie to profile photo using a face-similarity API (AWS Rekognition or similar). Set `is_verified = true` on match. Show a "Verified" badge in the swipe card.

---

## Onboarding

### ONB-01 · Profile completion not gated before swiping · P1
**File:** `app/routers/matchmaking.py`, `DatingApp/Sources/Features/Discovery/SwipeView.swift`  
A user can complete sign-up with only an email/password, skip photo upload, skip age/gender, and immediately start swiping. They appear as a blank card to other users. Other users swipe on them and get no meaningful profile to evaluate.  
**Fix:** Backend: `GET /matchmaking/potential-matches` returns `{"error": "profile_incomplete", "missing": ["photo", "age", "gender"]}` if any required fields are null. iOS: check for this error on app launch; redirect incomplete users to the profile completion flow before showing the swipe stack.

### ONB-02 · Values questionnaire is optional · P1
**File:** `app/routers/questionnaire.py`, `DatingApp/Sources/Features/Main/MainTabView.swift`  
The questionnaire is accessible from the Profile tab but not prompted on first launch. Users who skip it get ML compatibility scores calculated entirely from defaults (all 0.5), making the matchmaking no better than random for their first week.  
**Fix:** On first launch after profile completion, present `ValuesQuestionnaireView` as a required modal before the swipe stack is accessible. Allow skipping with a clear "You can complete this later" CTA that persists the prompt.

### ONB-03 · No mandatory profile photo · P2
**File:** `app/models.py:39` (`profile_image_url` nullable)  
Users can complete all other onboarding steps with no photo. They appear as a blank silhouette in the swipe stack, which other users immediately pass on.  
**Fix:** Make `profile_image_url` NOT NULL in the DB schema (with a migration). Require at least one photo before the profile can be marked `profile_completed = true`.

### ONB-04 · No intro video support · P3
**File:** All profile models  
The app's video-first thesis would be strengthened by letting users record a short (15–30s) intro video on their profile. Other users can watch it before swiping.  
**Fix:** (Post-launch) Add `video_intro_url` to `User` model. Add upload endpoint using Twilio or S3 pre-signed URLs. Display in swipe card and profile detail view.

---

## Infrastructure

### INFRA-02 · No deployment pipeline · P1
**File:** Neither repo has a `Dockerfile`, `docker-compose.yml`, or CI/CD configuration  
There is no reproducible way to deploy the backend to a cloud environment. The only documented run method is `uvicorn ... --reload` on a developer laptop.  
**Fix:** Create a `Dockerfile` for the backend. Add a `docker-compose.yml` with postgres + backend services for local development. Set up GitHub Actions: run tests on PR, build Docker image on merge to main, push to container registry. Deploy to AWS ECS, Fly.io, or Railway.

### INFRA-03 · No health check endpoint · P2
**File:** `app/main.py`  
Load balancers and container orchestrators (ECS, Kubernetes) require a health endpoint to determine if the service is alive and ready to serve traffic.  
**Fix:** Add `GET /health` returning `{"status": "ok", "db": "connected"}` after executing a lightweight DB query (e.g., `SELECT 1`). Return 503 if DB is unreachable.

### INFRA-04 · No structured logging · P2
**Files:** All routers  
A mix of `print()` calls and `logging.logger` calls with no centralized configuration. In production, these go to stdout with no structured format, making them unsearchable in log aggregators (Datadog, CloudWatch, etc.).  
**Fix:** Configure logging once in `app/main.py` using Python's `logging.config.dictConfig`. Use JSON formatter (e.g., `python-json-logger`). Replace all `print()` calls with `logger.debug/info/warning`. Add request ID middleware to correlate logs per request.

### INFRA-05 · No monitoring or alerting · P2
**File:** No monitoring configuration exists  
There is no way to know if the backend goes down, if error rates spike, or if DB query latency degrades. No Sentry, no metrics, no dashboards.  
**Fix:** Add Sentry SDK for error tracking (`pip install sentry-sdk[fastapi]`). Add Prometheus metrics endpoint (`/metrics`) for latency, throughput, and error rates. Configure PagerDuty or equivalent for P0 alerts (5xx rate > 1%, latency p99 > 2s).

### INFRA-06 · Alembic migrations incomplete · P2
**File:** `alembic/` directory  
Alembic is configured but multiple schema changes (ML tables, scheduling SQL functions, constraint fixes) were applied as raw `.sql` files. A fresh database cannot be set up by running `alembic upgrade head` alone.  
**Fix:** Convert all pending `.sql` files to Alembic migrations. Document the full migration order. Make `alembic upgrade head` the single, authoritative setup step for any new environment.

### INFRA-07 · No feature flags · P3
**File:** All endpoints  
New features cannot be toggled at runtime. Rolling back a bad deploy requires a full redeployment. A/B testing is not possible.  
**Fix:** (Post-launch) Add a lightweight feature flag system. A simple implementation: a `feature_flags` table in PostgreSQL with `(flag_name, enabled_for_user_ids, enabled_percent)`. Check flags in critical paths (new matchmaking algorithm, new scheduling flow).

---

---

## Follow-Up Items (Post-April-2026 Audit)

The April 2026 re-audit confirmed that all P0 and most P1 items are closed. All follow-up items have since been resolved.

### FU-01 · No-show detection job missing · P1 · **FIXED 2026-04-17**
Added `detect_no_shows()` to `SchedulingMonitorService`. Runs every 5 min alongside expiry checks. Marks `no_show`, increments `no_show_count`, writes `BehavioralEvent`, and notifies the waiting partner via `notify_no_show_partner`.

### FU-02 · `timeRangeString` missing explicit timezone · P2 · **FIXED 2026-04-17**
Added `formatter.timeZone = .current` to `TimeSlot`, `ProposalTimeSlot`, and `CounterProposalTimeSlot` `timeRangeString` implementations in `SchedulingModels.swift`.

### FU-03 · `ProfileUpdate` schema missing input length limits · P2 · **FIXED 2026-04-17**
Added `Field(None, max_length=100)` to `name` and `Field(None, max_length=1000)` to `bio` in `ProfileUpdate` schema.

### FU-04 · iOS error handling not centralized · P2 · **FIXED 2026-04-17**
`HTTPErrorHandler` already existed in `BackendService.swift` and was wired into `SchedulingService`. Completed by: routing `VideoCallError.serverError` through `HTTPErrorHandler.userFacingMessage`; wiring `HTTPErrorHandler` into `SwipeViewModel`'s user-facing fetch error path; adding 429 to the retry-triggering status codes in `syncSwipeToBackend`.

---

## Recommended Sequencing

### Phase 1 — Before any real user sees the app
1. INFRA-01: Rotate credentials, set up secrets manager
2. SEC-01: Remove TEST_MODE backdoor
3. IOS-01: Remove fallback user ID 75
4. SEC-02: Set up HTTPS (even a basic nginx + Let's Encrypt is fine)
5. SEC-03: Fix CORS to not default to `*`
6. IOS-05: Fix timezone display in scheduling
7. SCHED-01: Apply `check_scheduling_conflict` SQL fix

### Phase 2 — Before inviting beta users
8. BE-03 + SCHED-02: Implement 48-hour match expiry
9. BE-01: Add call rating endpoint
10. BE-02: Add call end recording endpoint
11. BE-04 + BE-05 + SAFE-02 + SAFE-03: Complete block flow end-to-end
12. DB-01: Fix cascade deletes
13. ONB-01 + DB-03: Gate swipes on profile completion
14. INFRA-02: Basic deployment pipeline (Dockerfile + CI)
15. INFRA-05: Sentry error tracking

### Phase 3 — Before public launch
16. SAFE-01: Admin report review tooling
17. DB-02: Soft deletes for GDPR
18. BE-06: Populate match_outcomes throughout the funnel
19. SEC-04: Rate limiting
20. DB-04 + INFRA-06: Consolidate all migrations into Alembic
21. IOS-02: Swipe sync failure handling
22. IOS-04: Counter-proposal implementation
23. INFRA-03: Health check endpoint
24. INFRA-04: Structured logging

### Phase 4 — Polish (post-launch)
25. IOS-07: Image caching
26. IOS-08: Unread badge clearing
27. IOS-10: Twilio retry logic
28. DB-05: Add missing indexes
29. ONB-04: Intro video
30. VC-04: Call recording for moderation
31. INFRA-07: Feature flags
