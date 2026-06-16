
## 2026-06-06 Task: Structured reporting backend (REPORTING_CATEGORIES_SPEC Migration A)
**Branch:** feature/reporting-categories
**Files Modified:**
- `app/models.py` — Report.category (String+CHECK, 10-enum) + context; reason vestigial; ix_reports_status_category
- `app/schemas.py` — ReportCategory/ReportContext enums; ReportCreate(category,context); `other`→details≥10 validator; ScheduledCallResponse.other_user_firebase_uid
- `app/routers/reporting.py` — write category/context, per-pair 24h dedupe (409), 20/hour limit, details kept out of logs
- `app/routers/admin.py` — ?category=/?context= list filters; detail + user-context show category/context
- `app/routers/scheduling.py` — populate other_user_firebase_uid on call responses
- `alembic/versions/20260606_a1b2c3d4e5f6_add_report_category_and_context.py` (new) — Migration A
- `tests/test_reporting.py`, `tests/test_admin_reports.py` (new, spec deliverables), `tests/verify_reporting_live.py` (new, Postgres-backed) + pytest.ini

**Summary:** Backend half of structured reporting. Migration A applied to Postgres; 17/17 live checks pass (all 10 categories, 422 on bad enum/`other`-without-details, 409 cross-context dedupe, 400 self-report). The shared SQLite pytest harness is pre-broken (stale model imports + ARRAY column) so verification runs via a Postgres-backed TestClient script.
**Status:** completed (Migration B drop-reason deferred to separate PR).
---

## 2026-06-16 Task: Phase 9A — remove legacy scheduling endpoints, add match_expiring_soon cron, fix PG message mirror
**Branch:** feature/scheduling-v2
**Files Modified:**
- `app/routers/scheduling.py` — deleted legacy endpoints: schedule_call (POST /calls), extend_call, confirm_call, the commented-out proposal block, and all 5 /call-requests* Tier-1 endpoints; cleaned orphaned imports (ScheduledCallCreate) and stale comments. KEPT cancel_call (sensible for V2; references only valid ScheduledCall fields).
- `app/services/push_notification_service.py` — removed orphaned senders (zero call sites): notify_immediate_call_request, notify_call_reminder, notify_match_expiring, notify_no_show_partner.
- `app/services/match_state_service.py` — added notify_expiring_soon_matches(db): fires match_expiring_soon 24h before expiry (text_locked_at crossed 48h of the 72h window) for locked/active/none|no_show matches; tick-width dedup mirroring notify_text_window_nudges.
- `app/services/scheduling_monitor_service.py` — wired notify_expiring_soon_matches into the 300s check_all_matches loop.
- `app/routers/messaging.py` — fixed create_message_in_postgresql: resolve PG Conversation by participant PAIR (not the Firestore string id), create one if missing, drop the bogus firebase_id=conversation_id stamp. Caller passes sender_id/recipient_id.
- `tests/test_scheduling_v2_crons.py`, `tests/test_messaging_gate.py` — added 4 tests (expiring-soon fires once / skips young; mirror resolves-by-pair / creates-when-missing); updated existing mirror test to new signature.

**Summary:** Removed dead legacy scheduling/call-request code + orphaned push senders; wired the missing match_expiring_soon cron with once-per-match dedup; fixed the long-standing silent no-op Postgres message mirror by resolving the conversation via the user pair. App imports clean; 112 targeted tests pass; no stale references.
**Status:** completed
---
