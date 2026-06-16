-- seed_scheduling_v2.sql
-- Idempotent, re-runnable V2 scheduling seed for the Scheduling V2 backend.
--
-- Goal: give the iOS sim (logged in as Andrew Zhang #5) a SPREAD of V2 match-card
-- states to drive the E2E, plus reset the spec's E2E matches 57/60 if they exist.
--
-- V2 match dims: text_state ∈ {open,locked,archived}
--                call_status ∈ {none,proposal_pending,scheduled,in_progress,
--                               pending_survey,completed,no_show}
--                lifecycle   ∈ {active,terminated,expired}
--
-- States set here:
--   match 2  (Lena #2 ↔ Andrew #5)  -> (open,  none, active)  ACTIVE / Texting
--   match 37 (Andrew #5 ↔ Jamie #75) -> (locked,none, active)  needs-schedule
--   match 57 (Alex #87 ↔ Mia #85)    -> (open,  none, active)  fresh texting (spec E2E)
--   match 60 (Jordan #89 ↔ Riley #90)-> (open,  none, active)  fresh texting (spec E2E)
--
-- NOTE: the legacy `trigger_update_call_preferences` workaround from
-- seed_scheduling_audit.sql is intentionally OMITTED — that trigger was DROPPED by
-- the V2 migration (verified: it no longer exists on scheduled_calls). Do not re-add.
--
-- Fully re-runnable: clean V2 child rows via DELETE then drive parents via UPDATE.

BEGIN;

----------------------------------------------------------------------
-- 0. Clean V2 child rows for all touched matches (idempotent reset).
--    Order matters (FK dependencies):
--      video_call_rooms -> scheduled_calls (fk_rooms_scheduled_call, no cascade)
--      no_show_events   -> scheduled_calls (cascade, but explicit for clarity)
--      then scheduled_calls, then video_call_proposals.
--    call_ratings -> scheduled_calls is ON DELETE CASCADE (handled implicitly).
----------------------------------------------------------------------
DELETE FROM video_call_rooms
WHERE scheduled_call_id IN (
    SELECT id FROM scheduled_calls WHERE match_id IN (2, 37, 57, 60)
);
DELETE FROM no_show_events       WHERE match_id IN (2, 37, 57, 60);
DELETE FROM scheduled_calls      WHERE match_id IN (2, 37, 57, 60);
DELETE FROM video_call_proposals WHERE match_id IN (2, 37, 57, 60);

----------------------------------------------------------------------
-- 1. Reactivate Andrew's matches (2 and 37): make sure they're visible.
----------------------------------------------------------------------
UPDATE matches
SET status       = 'accepted',
    user1_status = 'active',
    user2_status = 'active',
    deleted_at   = NULL
WHERE id IN (2, 37);

----------------------------------------------------------------------
-- 2. match 2 (Lena ↔ Andrew): clean ACTIVE / Texting (open, none, active).
----------------------------------------------------------------------
UPDATE matches
SET text_state                      = 'open',
    call_status                     = 'none',
    lifecycle                       = 'active',
    text_locked_at                  = NULL,
    text_unlocked_at                = NULL,
    expires_at                      = NULL,
    created_at                      = NOW(),
    exit_survey_user_a_response     = NULL,
    exit_survey_user_a_responded_at = NULL,
    exit_survey_user_b_response     = NULL,
    exit_survey_user_b_responded_at = NULL,
    contact_reveal_unlocked         = FALSE,
    contact_revealed_to_user_a_at   = NULL,
    contact_revealed_to_user_b_at   = NULL
WHERE id = 2;

----------------------------------------------------------------------
-- 3. match 37 (Andrew ↔ Jamie): locked / needs-schedule
--    (locked, none, active). text locked 1h ago, 71h left in the 72h window.
--    Drives the "Schedule a video date" action-needed card + text-lock banner.
----------------------------------------------------------------------
UPDATE matches
SET text_state                      = 'locked',
    call_status                     = 'none',
    lifecycle                       = 'active',
    text_locked_at                  = NOW() - INTERVAL '1 hour',
    text_unlocked_at                = NULL,
    expires_at                      = NOW() + INTERVAL '71 hours',
    exit_survey_user_a_response     = NULL,
    exit_survey_user_a_responded_at = NULL,
    exit_survey_user_b_response     = NULL,
    exit_survey_user_b_responded_at = NULL,
    contact_reveal_unlocked         = FALSE,
    contact_revealed_to_user_a_at   = NULL,
    contact_revealed_to_user_b_at   = NULL
WHERE id = 37;

----------------------------------------------------------------------
-- 4. Spec E2E matches 57 (Alex ↔ Mia) and 60 (Jordan ↔ Riley):
--    reset to fresh (open, none, active) texting. Guarded so the script
--    stays clean if these rows ever go away. (Child rows already cleaned above.)
----------------------------------------------------------------------
UPDATE matches
SET status                          = 'accepted',
    user1_status                    = 'active',
    user2_status                    = 'active',
    deleted_at                      = NULL,
    text_state                      = 'open',
    call_status                     = 'none',
    lifecycle                       = 'active',
    text_locked_at                  = NULL,
    text_unlocked_at                = NULL,
    expires_at                      = NULL,
    created_at                      = NOW(),
    exit_survey_user_a_response     = NULL,
    exit_survey_user_a_responded_at = NULL,
    exit_survey_user_b_response     = NULL,
    exit_survey_user_b_responded_at = NULL,
    contact_reveal_unlocked         = FALSE,
    contact_revealed_to_user_a_at   = NULL,
    contact_revealed_to_user_b_at   = NULL
WHERE id IN (57, 60);

COMMIT;

----------------------------------------------------------------------
-- Verification: the three V2 dims for every touched match.
----------------------------------------------------------------------
SELECT id, user_id, matched_user_id, status,
       text_state, call_status, lifecycle,
       text_locked_at, expires_at, contact_reveal_unlocked
FROM matches
WHERE id IN (2, 37, 57, 60)
ORDER BY id;

-- Confirm child tables are empty for these matches.
SELECT 'video_call_proposals' AS tbl, count(*) AS rows FROM video_call_proposals WHERE match_id IN (2,37,57,60)
UNION ALL
SELECT 'scheduled_calls', count(*) FROM scheduled_calls WHERE match_id IN (2,37,57,60)
UNION ALL
SELECT 'no_show_events', count(*) FROM no_show_events WHERE match_id IN (2,37,57,60);
