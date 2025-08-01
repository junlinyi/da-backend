-- Fix the find_common_availability function
-- The bug is that it references 'd.day_of_week' but 'd' is not defined
-- It should be 'w.day_of_week' since 'w' is the alias for user_weekly_availability

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
BEGIN
    RETURN QUERY
    WITH user1_availability AS (
        -- Get user1's availability (weekly + overrides)
        SELECT 
            CASE 
                WHEN o.date IS NOT NULL THEN o.date
                ELSE p_start_date + (w.day_of_week - EXTRACT(DOW FROM p_start_date)::INTEGER) % 7
            END as available_date,
            COALESCE(o.start_time, w.start_time) as slot_start,
            COALESCE(o.end_time, w.end_time) as slot_end
        FROM user_weekly_availability w
        LEFT JOIN user_availability_overrides o ON 
            w.user_id = o.user_id 
            AND o.date BETWEEN p_start_date AND p_end_date
            AND o.start_time = w.start_time
        WHERE w.user_id = p_user1_id
          AND (o.date IS NULL OR (o.date BETWEEN p_start_date AND p_end_date))
    ),
    user2_availability AS (
        -- Get user2's availability (weekly + overrides)
        SELECT 
            CASE 
                WHEN o.date IS NOT NULL THEN o.date
                ELSE p_start_date + (w.day_of_week - EXTRACT(DOW FROM p_start_date)::INTEGER) % 7
            END as available_date,
            COALESCE(o.start_time, w.start_time) as slot_start,
            COALESCE(o.end_time, w.end_time) as slot_end
        FROM user_weekly_availability w
        LEFT JOIN user_availability_overrides o ON 
            w.user_id = o.user_id 
            AND o.date BETWEEN p_start_date AND p_end_date
            AND o.start_time = w.start_time
        WHERE w.user_id = p_user2_id
          AND (o.date IS NULL OR (o.date BETWEEN p_start_date AND p_end_date))
    ),
    common_slots AS (
        -- Find overlapping time slots
        SELECT 
            u1.available_date,
            GREATEST(u1.slot_start, u2.slot_start) as start_time,
            LEAST(u1.slot_end, u2.slot_end) as end_time
        FROM user1_availability u1
        JOIN user2_availability u2 ON 
            u1.available_date = u2.available_date
            AND u1.slot_start < u2.slot_end
            AND u1.slot_end > u2.slot_start
        WHERE u1.available_date BETWEEN p_start_date AND p_end_date
    )
    SELECT 
        cs.available_date as date,
        cs.start_time,
        cs.end_time,
        TRUE as user1_available,
        TRUE as user2_available
    FROM common_slots cs
    WHERE cs.end_time > cs.start_time  -- Ensure valid time slots
    ORDER BY cs.available_date, cs.start_time;
END;
$$ LANGUAGE plpgsql; 