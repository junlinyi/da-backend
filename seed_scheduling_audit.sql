-- seed_scheduling_audit.sql
-- Populates an auditable scheduling state for the Red Thread UI audit
-- (UI_APPEARANCE_AUDIT bucket A — "scheduling populated").
--
-- Run:  PGPASSWORD=securepassword psql -h localhost -U dating_user -d dating_app -f seed_scheduling_audit.sql
--
-- What it seeds (LEGACY two-tier model — SCHEDULING_V2 is not migrated yet):
--   • Match 2  (Lena Huynh 2 ↔ Andrew Zhang 5): reactivated + ONE upcoming
--     scheduled call → renders the "Upcoming" RTMatchCard (lockedScheduled).
--   • Match 37 (Andrew Zhang 5 ↔ Jamie Zhang 75): reactivated, NO call →
--     renders an unscheduled RTMatchCard + opens SchedulingPickerView (72h picker).
--
-- Idempotent / re-runnable: always future-dates the call and cleans its own
-- seeded row (sentinel call_room_id) before inserting.
--
-- NOTE (audit caveats, not fixable by seeding):
--   1. The RTTimezoneBanner (finding C3) stays SUPPRESSED — SchedulingView passes
--      nil because the iOS Match model has no peer city/timezone yet (a code
--      change, per SCHEDULING_V2). Andrew & Lena are both UTC anyway (no delta).
--   2. Cards render via a legacy→RTMatchCardState heuristic; the full V2 state
--      machine (text_state/call_status/lifecycle, video_call_proposals) is unbuilt.

BEGIN;

-- 1. Reactivate the two matches (both currently blocked/expired).
UPDATE matches
   SET status = 'accepted', user1_status = 'active', user2_status = 'active', deleted_at = NULL
 WHERE id IN (2, 37);

-- Match 37 must be "fresh" to surface as an unscheduled match: the
-- /scheduling unscheduled endpoint only returns matches created within the
-- last 48h (legacy Tier-2 window). Bump it so the unscheduled RTMatchCard
-- renders and tapping it opens SchedulingPickerView (the 72h picker).
UPDATE matches SET created_at = NOW() WHERE id = 37;

-- 2. Upcoming scheduled call on match 2 — clean prior seed, then insert.
-- The `trigger_update_call_preferences` trigger references a dropped table
-- (`user_match_call_preferences`) and 500s on any insert, so disable it for
-- the seed insert. (This is a latent backend bug — flagged separately; it
-- would break real scheduling on this DB too.)
ALTER TABLE scheduled_calls DISABLE TRIGGER trigger_update_call_preferences;

DELETE FROM scheduled_calls WHERE call_room_id = 'audit-seed-match2';

INSERT INTO scheduled_calls (
    match_id, user1_id, user2_id,
    scheduled_start_utc, scheduled_end_utc, duration_minutes,
    status, user1_confirmed, user2_confirmed, user1_confirmed_at, user2_confirmed_at,
    call_room_id, reschedule_count, user1_notified, user2_notified, reminder_sent,
    created_at, updated_at
) VALUES (
    2, 2, 5,
    date_trunc('day', NOW()) + INTERVAL '2 days 19 hours',
    date_trunc('day', NOW()) + INTERVAL '2 days 19 hours 30 minutes',
    30,
    'scheduled', TRUE, TRUE, NOW(), NOW(),
    'audit-seed-match2', 0, TRUE, TRUE, FALSE,
    NOW(), NOW()
);

ALTER TABLE scheduled_calls ENABLE TRIGGER trigger_update_call_preferences;

COMMIT;

-- Verification (printed after commit)
\echo '--- matches 2 & 37 ---'
SELECT id, user_id, matched_user_id, status, user1_status, user2_status FROM matches WHERE id IN (2,37) ORDER BY id;
\echo '--- seeded scheduled call ---'
SELECT id, match_id, user1_id, user2_id, scheduled_start_utc, status FROM scheduled_calls WHERE call_room_id = 'audit-seed-match2';
