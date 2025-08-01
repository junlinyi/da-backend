-- Add scheduling constraints and tracking tables

-- 1. Add unique constraints to prevent double booking
-- Prevent a user from having multiple scheduled calls at the same time
CREATE UNIQUE INDEX IF NOT EXISTS idx_user1_time_conflict 
ON scheduled_calls (user1_id, scheduled_start_utc) 
WHERE status IN ('scheduled', 'in_progress');

CREATE UNIQUE INDEX IF NOT EXISTS idx_user2_time_conflict 
ON scheduled_calls (user2_id, scheduled_start_utc) 
WHERE status IN ('scheduled', 'in_progress');

-- 2. Create table to track user-match call preferences
CREATE TABLE IF NOT EXISTS user_match_call_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    matched_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Call preference status
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- 'pending', 'wants_to_call', 'doesnt_want_to_call', 'already_called'
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Metadata
    last_common_availability_check TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_notification_sent TIMESTAMP WITH TIME ZONE,
    
    -- Unique constraint to prevent duplicate preferences
    UNIQUE(user_id, matched_user_id)
);

-- 3. Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_call_preferences_status ON user_match_call_preferences(status);
CREATE INDEX IF NOT EXISTS idx_call_preferences_last_check ON user_match_call_preferences(last_common_availability_check);
CREATE INDEX IF NOT EXISTS idx_call_preferences_user ON user_match_call_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_call_preferences_matched ON user_match_call_preferences(matched_user_id);

-- 4. Add function to automatically create call preferences when matches are made
CREATE OR REPLACE FUNCTION create_call_preferences_for_match()
RETURNS TRIGGER AS $$
BEGIN
    -- When a match is created, create call preferences for both users
    INSERT INTO user_match_call_preferences (user_id, matched_user_id, status)
    VALUES (NEW.user_id, NEW.matched_user_id, 'pending')
    ON CONFLICT (user_id, matched_user_id) DO NOTHING;
    
    INSERT INTO user_match_call_preferences (user_id, matched_user_id, status)
    VALUES (NEW.matched_user_id, NEW.user_id, 'pending')
    ON CONFLICT (user_id, matched_user_id) DO NOTHING;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 5. Create trigger to automatically create call preferences for new matches
DROP TRIGGER IF EXISTS trigger_create_call_preferences ON matches;
CREATE TRIGGER trigger_create_call_preferences
    AFTER INSERT ON matches
    FOR EACH ROW
    EXECUTE FUNCTION create_call_preferences_for_match();

-- 6. Add function to update call preferences when calls are scheduled
CREATE OR REPLACE FUNCTION update_call_preferences_on_schedule()
RETURNS TRIGGER AS $$
BEGIN
    -- When a call is scheduled, update both users' preferences to 'already_called'
    UPDATE user_match_call_preferences 
    SET status = 'already_called', updated_at = NOW()
    WHERE (user_id = NEW.user1_id AND matched_user_id = NEW.user2_id)
       OR (user_id = NEW.user2_id AND matched_user_id = NEW.user1_id);
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 7. Create trigger to update call preferences when calls are scheduled
DROP TRIGGER IF EXISTS trigger_update_call_preferences ON scheduled_calls;
CREATE TRIGGER trigger_update_call_preferences
    AFTER INSERT ON scheduled_calls
    FOR EACH ROW
    EXECUTE FUNCTION update_call_preferences_on_schedule();

-- 8. Add function to check for scheduling conflicts
CREATE OR REPLACE FUNCTION check_scheduling_conflict(
    p_user_id INTEGER,
    p_start_time TIMESTAMP WITH TIME ZONE,
    p_end_time TIMESTAMP WITH TIME ZONE
) RETURNS BOOLEAN AS $$
DECLARE
    conflict_exists BOOLEAN;
BEGIN
    SELECT EXISTS(
        SELECT 1 FROM scheduled_calls 
        WHERE (user1_id = p_user_id OR user2_id = p_user_id)
          AND status IN ('scheduled', 'in_progress')
          AND (
              (scheduled_start_utc < p_end_time AND scheduled_end_utc > p_start_time)
          )
    ) INTO conflict_exists;
    
    RETURN conflict_exists;
END;
$$ LANGUAGE plpgsql;

-- 9. Add function to find common availability between two users
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
                ELSE p_start_date + (d.day_of_week - EXTRACT(DOW FROM p_start_date)::INTEGER) % 7
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
                ELSE p_start_date + (d.day_of_week - EXTRACT(DOW FROM p_start_date)::INTEGER) % 7
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

-- Show the new tables and constraints
SELECT 'Constraints and tables created successfully' as result; 