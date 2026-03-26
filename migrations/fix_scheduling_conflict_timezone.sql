-- Migration: align check_scheduling_conflict with find_common_availability
--
-- PROBLEM: check_scheduling_conflict used date_trunc('week') which returns Monday
-- as the week start, while user_override_availability stores rows keyed to Sunday.
-- This caused a lookup miss — overrides were ignored — producing false "unavailable"
-- results and spurious 409 conflicts when the conflict check ran against slots that
-- find_common_availability had already confirmed as free.
--
-- FIX: Both functions now use get_week_start_sunday() and the same
-- override-first LEFT JOIN / COALESCE pattern.
--
-- Run once against the dating_app database:
--   docker exec -i <postgres_container> psql -U dating_user -d dating_app \
--     < migrations/fix_scheduling_conflict_timezone.sql

-- Helper: Sunday-based week start (override rows are keyed this way)
CREATE OR REPLACE FUNCTION get_week_start_sunday(p_date DATE)
RETURNS DATE AS $$
BEGIN
    -- EXTRACT(dow) returns 0 for Sunday; subtracting it gives the preceding Sunday.
    RETURN p_date - EXTRACT(dow FROM p_date)::integer;
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- fix check_scheduling_conflict to use override-first logic matching find_common_availability
CREATE OR REPLACE FUNCTION check_scheduling_conflict(
    p_user_id   INTEGER,
    p_start_time TIMESTAMP WITH TIME ZONE,
    p_end_time   TIMESTAMP WITH TIME ZONE
) RETURNS BOOLEAN AS $$
DECLARE
    call_conflict_exists BOOLEAN;
    user_is_available    BOOLEAN;
    check_date           DATE;
    check_day_of_week    INTEGER;
    check_hour           INTEGER;
    check_minute         INTEGER;
    week_start           DATE;
    utc_start_time       TIMESTAMP;
BEGIN
    -- 1. Hard conflict: another scheduled or in-progress call overlaps this window
    SELECT EXISTS(
        SELECT 1 FROM scheduled_calls
        WHERE (user1_id = p_user_id OR user2_id = p_user_id)
          AND status IN ('scheduled', 'in_progress')
          AND (scheduled_start_utc < p_end_time AND scheduled_end_utc > p_start_time)
    ) INTO call_conflict_exists;

    IF call_conflict_exists THEN
        RETURN TRUE;
    END IF;

    -- 2. Availability check — identical logic to find_common_availability
    utc_start_time    := p_start_time AT TIME ZONE 'UTC';
    check_date        := utc_start_time::date;
    check_day_of_week := EXTRACT(dow    FROM utc_start_time)::integer;
    check_hour        := EXTRACT(hour   FROM utc_start_time)::integer;
    check_minute      := CASE
                             WHEN EXTRACT(minute FROM utc_start_time)::integer < 30 THEN 0
                             ELSE 30
                         END;
    week_start := get_week_start_sunday(check_date);

    -- Override-first: if an override row exists for this week it takes precedence;
    -- otherwise fall back to the default availability row.
    SELECT COALESCE(o.is_available, d.is_available, FALSE) INTO user_is_available
    FROM user_default_availability d
    LEFT JOIN user_override_availability o ON
            o.user_id       = d.user_id
        AND o.day_of_week   = d.day_of_week
        AND o.hour          = d.hour
        AND o.minute        = d.minute
        AND o.week_start_date = week_start
    WHERE d.user_id       = p_user_id
      AND d.day_of_week   = check_day_of_week
      AND d.hour          = check_hour
      AND d.minute        = check_minute;

    -- No row at all → user has not set availability for this slot → treat as unavailable
    IF user_is_available IS NULL THEN
        user_is_available := FALSE;
    END IF;

    -- TRUE means "conflict exists" (i.e. user is NOT available)
    RETURN NOT user_is_available;
END;
$$ LANGUAGE plpgsql;


-- Rebuild find_common_availability to use the same Sunday week-start helper.
-- (In practice this function already uses the correct logic; this is a safety
--  re-apply so both functions are guaranteed to be in sync after this migration.)
CREATE OR REPLACE FUNCTION find_common_availability(
    p_user1_id  INTEGER,
    p_user2_id  INTEGER,
    p_start_date DATE,
    p_end_date   DATE
) RETURNS TABLE(
    date            DATE,
    start_time      TIME,
    end_time        TIME,
    user1_available BOOLEAN,
    user2_available BOOLEAN
) AS $$
DECLARE
    week_start DATE;
BEGIN
    week_start := get_week_start_sunday(p_start_date);

    RETURN QUERY
    WITH user1_availability AS (
        SELECT d.day_of_week, d.hour, d.minute,
               COALESCE(o.is_available, d.is_available) AS is_available
        FROM user_default_availability d
        LEFT JOIN user_override_availability o ON
                o.user_id       = d.user_id
            AND o.day_of_week   = d.day_of_week
            AND o.hour          = d.hour
            AND o.minute        = d.minute
            AND o.week_start_date = week_start
        WHERE d.user_id = p_user1_id
    ),
    user2_availability AS (
        SELECT d.day_of_week, d.hour, d.minute,
               COALESCE(o.is_available, d.is_available) AS is_available
        FROM user_default_availability d
        LEFT JOIN user_override_availability o ON
                o.user_id       = d.user_id
            AND o.day_of_week   = d.day_of_week
            AND o.hour          = d.hour
            AND o.minute        = d.minute
            AND o.week_start_date = week_start
        WHERE d.user_id = p_user2_id
    ),
    date_series AS (
        SELECT generate_series(p_start_date, p_end_date, '1 day'::interval)::date AS check_date
    ),
    expanded_availability AS (
        SELECT ds.check_date, u1.hour, u1.minute,
               u1.is_available AS user1_available,
               u2.is_available AS user2_available
        FROM date_series ds
        CROSS JOIN user1_availability u1
        JOIN user2_availability u2 ON
                u1.day_of_week = u2.day_of_week
            AND u1.hour        = u2.hour
            AND u1.minute      = u2.minute
        WHERE EXTRACT(dow FROM ds.check_date)::integer = u1.day_of_week
          AND u1.is_available = TRUE
          AND u2.is_available = TRUE
    ),
    common_slots AS (
        -- First 15-minute block of each 30-minute availability slot
        SELECT DISTINCT ea.check_date,
               make_time(ea.hour, ea.minute, 0)      AS slot_start,
               make_time(ea.hour, ea.minute + 15, 0) AS slot_end,
               TRUE AS user1_available,
               TRUE AS user2_available
        FROM expanded_availability ea
        UNION ALL
        -- Second 15-minute block
        SELECT DISTINCT ea.check_date,
               CASE WHEN ea.minute + 15 >= 60
                    THEN make_time(ea.hour + 1, 0, 0)
                    ELSE make_time(ea.hour, ea.minute + 15, 0)
               END AS slot_start,
               CASE WHEN ea.minute + 30 >= 60
                    THEN make_time(ea.hour + 1, 15, 0)
                    ELSE make_time(ea.hour, ea.minute + 30, 0)
               END AS slot_end,
               TRUE AS user1_available,
               TRUE AS user2_available
        FROM expanded_availability ea
        WHERE ea.minute <= 30
          AND (ea.hour < 23 OR (ea.hour = 23 AND ea.minute < 30))
    )
    SELECT cs.check_date, cs.slot_start, cs.slot_end,
           cs.user1_available, cs.user2_available
    FROM common_slots cs
    WHERE cs.slot_end <= '23:59:59'::time
    ORDER BY cs.check_date, cs.slot_start;
END;
$$ LANGUAGE plpgsql;


-- find_immediate_common_availability wraps find_common_availability; no changes needed
-- other than ensuring it references the updated function above.
CREATE OR REPLACE FUNCTION find_immediate_common_availability(
    p_user1_id INTEGER,
    p_user2_id INTEGER
) RETURNS TABLE(
    date            DATE,
    start_time      TIME,
    end_time        TIME,
    user1_available BOOLEAN,
    user2_available BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT fca.date, fca.start_time, fca.end_time,
           fca.user1_available, fca.user2_available
    FROM find_common_availability(
        p_user1_id,
        p_user2_id,
        CURRENT_DATE,
        (CURRENT_DATE + INTERVAL '7 days')::date
    ) fca
    ORDER BY fca.date, fca.start_time
    LIMIT 3;
END;
$$ LANGUAGE plpgsql;
