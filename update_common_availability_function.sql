-- Updated find_common_availability function to use When2Meet override-first approach
-- This function prioritizes user_override_availability over user_default_availability
-- for more accurate availability calculation
--
-- IMPORTANT: Uses Sunday as week start (matching override storage), NOT date_trunc('week') which returns Monday!

-- Helper function to get week start as Sunday (matching how overrides are stored)
CREATE OR REPLACE FUNCTION get_week_start_sunday(p_date DATE)
RETURNS DATE AS $$
BEGIN
    -- EXTRACT(dow) returns 0 for Sunday, so subtract dow days to get Sunday
    RETURN p_date - EXTRACT(dow FROM p_date)::integer;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

CREATE OR REPLACE FUNCTION find_common_availability(
    p_user1_id INTEGER,
    p_user2_id INTEGER,
    p_start_date DATE,
    p_end_date DATE
) RETURNS TABLE(
    date DATE,
    start_time TIME,
    end_time TIME,
    user1_available BOOLEAN,
    user2_available BOOLEAN
) AS $$
DECLARE
    week_start DATE;
BEGIN
    -- Calculate week start as SUNDAY (matching how overrides are stored)
    week_start := get_week_start_sunday(p_start_date);

    RETURN QUERY
    WITH user1_availability AS (
        -- Get user1's availability using override-first approach
        SELECT
            d.day_of_week,
            d.hour,
            d.minute,
            -- Use override availability if exists, otherwise use default
            COALESCE(o.is_available, d.is_available) as is_available
        FROM user_default_availability d
        LEFT JOIN user_override_availability o ON
            d.user_id = o.user_id
            AND d.day_of_week = o.day_of_week
            AND d.hour = o.hour
            AND d.minute = o.minute
            AND o.week_start_date = week_start
        WHERE d.user_id = p_user1_id
    ),
    user2_availability AS (
        -- Get user2's availability using override-first approach
        SELECT
            d.day_of_week,
            d.hour,
            d.minute,
            -- Use override availability if exists, otherwise use default
            COALESCE(o.is_available, d.is_available) as is_available
        FROM user_default_availability d
        LEFT JOIN user_override_availability o ON
            d.user_id = o.user_id
            AND d.day_of_week = o.day_of_week
            AND d.hour = o.hour
            AND d.minute = o.minute
            AND o.week_start_date = week_start
        WHERE d.user_id = p_user2_id
    ),
    date_series AS (
        -- Generate all dates in the requested range
        SELECT 
            generate_series(p_start_date, p_end_date, '1 day'::interval)::date as check_date
    ),
    expanded_availability AS (
        -- Convert day_of_week to actual dates and create 30-minute time slots
        SELECT 
            ds.check_date,
            u1.hour,
            u1.minute,
            u1.is_available as user1_available,
            u2.is_available as user2_available
        FROM date_series ds
        CROSS JOIN user1_availability u1
        JOIN user2_availability u2 ON 
            u1.day_of_week = u2.day_of_week
            AND u1.hour = u2.hour
            AND u1.minute = u2.minute
        WHERE EXTRACT(dow FROM ds.check_date)::integer = u1.day_of_week
          AND u1.is_available = true 
          AND u2.is_available = true
    ),
    common_slots AS (
        -- Create 15-minute time blocks from 30-minute availability slots
        SELECT DISTINCT
            ea.check_date,
            make_time(ea.hour, ea.minute, 0) as slot_start,
            make_time(ea.hour, ea.minute + 15, 0) as slot_end_15min,
            true as user1_available,
            true as user2_available
        FROM expanded_availability ea
        UNION ALL
        SELECT DISTINCT
            ea.check_date,
            CASE 
                WHEN ea.minute + 15 >= 60 THEN make_time(ea.hour + 1, 0, 0)
                ELSE make_time(ea.hour, ea.minute + 15, 0)
            END as slot_start,
            CASE 
                WHEN ea.minute + 30 >= 60 THEN make_time(ea.hour + 1, 15, 0)
                ELSE make_time(ea.hour, ea.minute + 30, 0)
            END as slot_end_15min,
            true as user1_available,
            true as user2_available
        FROM expanded_availability ea
        WHERE ea.minute <= 30  -- Prevent going beyond valid times
          AND (ea.hour < 23 OR (ea.hour = 23 AND ea.minute < 30))  -- Don't exceed day boundaries
    )
    SELECT 
        cs.check_date as date,
        cs.slot_start as start_time,
        cs.slot_end_15min as end_time,
        cs.user1_available,
        cs.user2_available
    FROM common_slots cs
    WHERE cs.slot_end_15min <= '23:59:59'::time  -- Ensure we don't exceed day boundaries
    ORDER BY cs.check_date, cs.slot_start;
END;
$$ LANGUAGE plpgsql;

-- Fix check_scheduling_conflict to use the same override-first availability logic as find_common_availability
-- This resolves timezone and week-start mismatches that caused false 409 conflicts
CREATE OR REPLACE FUNCTION check_scheduling_conflict(
    p_user_id INTEGER,
    p_start_time TIMESTAMP WITH TIME ZONE,
    p_end_time TIMESTAMP WITH TIME ZONE
) RETURNS BOOLEAN AS $$
DECLARE
    call_conflict_exists BOOLEAN;
    user_is_available BOOLEAN;
    check_date DATE;
    check_day_of_week INTEGER;
    check_hour INTEGER;
    check_minute INTEGER;
    week_start DATE;
    utc_start_time TIMESTAMP;
BEGIN
    -- 1. Check for conflicts with existing scheduled calls
    SELECT EXISTS(
        SELECT 1 FROM scheduled_calls
        WHERE (user1_id = p_user_id OR user2_id = p_user_id)
          AND status IN ('scheduled', 'in_progress')
          AND (scheduled_start_utc < p_end_time AND scheduled_end_utc > p_start_time)
    ) INTO call_conflict_exists;

    IF call_conflict_exists THEN
        RETURN TRUE;
    END IF;

    -- 2. Check user availability using IDENTICAL logic to find_common_availability
    -- Convert to UTC timestamp for consistent extraction
    utc_start_time := p_start_time AT TIME ZONE 'UTC';

    check_date := utc_start_time::date;
    check_day_of_week := EXTRACT(dow FROM utc_start_time)::integer;  -- 0=Sunday, 6=Saturday
    check_hour := EXTRACT(hour FROM utc_start_time)::integer;

    -- Round minute to 30-minute slot (0 or 30) to match availability table structure
    check_minute := CASE
        WHEN EXTRACT(minute FROM utc_start_time)::integer < 30 THEN 0
        ELSE 30
    END;

    -- Calculate week start as SUNDAY (matching how overrides are stored)
    -- NOT using date_trunc('week') which returns Monday!
    week_start := get_week_start_sunday(check_date);

    -- Use IDENTICAL logic to find_common_availability:
    -- LEFT JOIN override onto default, COALESCE to get effective availability
    SELECT COALESCE(o.is_available, d.is_available, FALSE) INTO user_is_available
    FROM user_default_availability d
    LEFT JOIN user_override_availability o ON
        d.user_id = o.user_id
        AND d.day_of_week = o.day_of_week
        AND d.hour = o.hour
        AND d.minute = o.minute
        AND o.week_start_date = week_start
    WHERE d.user_id = p_user_id
      AND d.day_of_week = check_day_of_week
      AND d.hour = check_hour
      AND d.minute = check_minute;

    -- If no availability record found at all, assume not available
    IF user_is_available IS NULL THEN
        user_is_available := FALSE;
    END IF;

    -- Return TRUE if there's a conflict (user is NOT available)
    RETURN NOT user_is_available;
END;
$$ LANGUAGE plpgsql;

-- Create a simplified version that returns fewer results for the immediate match popup
CREATE OR REPLACE FUNCTION find_immediate_common_availability(
    p_user1_id INTEGER,
    p_user2_id INTEGER
) RETURNS TABLE(
    date DATE,
    start_time TIME,
    end_time TIME,
    user1_available BOOLEAN,
    user2_available BOOLEAN
) AS $$
BEGIN
    -- Find common availability for the next 7 days, return max 3 earliest slots
    RETURN QUERY
    SELECT 
        fca.date,
        fca.start_time,
        fca.end_time,
        fca.user1_available,
        fca.user2_available
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