-- Video Call Scheduling Database Schema
-- Handles timezone-aware scheduling with 30-minute slots and 15-minute calls

-- 1. User Availability Tables
CREATE TABLE IF NOT EXISTS user_weekly_availability (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day_of_week INTEGER NOT NULL CHECK (day_of_week >= 0 AND day_of_week <= 6), -- 0=Sunday, 6=Saturday
    start_time TIME NOT NULL, -- Local time in user's timezone
    end_time TIME NOT NULL, -- Local time in user's timezone
    is_available BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, day_of_week, start_time, end_time)
);

CREATE TABLE IF NOT EXISTS user_availability_overrides (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date DATE NOT NULL, -- Specific date
    start_time TIME NOT NULL, -- Local time in user's timezone
    end_time TIME NOT NULL, -- Local time in user's timezone
    is_available BOOLEAN NOT NULL DEFAULT true,
    override_type VARCHAR(20) NOT NULL DEFAULT 'override', -- 'override', 'block'
    reason VARCHAR(255), -- Optional reason for override
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, date, start_time, end_time)
);

-- 2. User Timezone Information
CREATE TABLE IF NOT EXISTS user_timezones (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    timezone VARCHAR(50) NOT NULL DEFAULT 'UTC', -- e.g., 'America/New_York'
    timezone_offset INTEGER NOT NULL DEFAULT 0, -- Offset in minutes from UTC
    dst_enabled BOOLEAN NOT NULL DEFAULT false, -- Daylight saving time enabled
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Scheduled Video Calls
CREATE TABLE IF NOT EXISTS scheduled_calls (
    id SERIAL PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    user1_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user2_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Call timing (stored in UTC for consistency)
    scheduled_start_utc TIMESTAMP WITH TIME ZONE NOT NULL,
    scheduled_end_utc TIMESTAMP WITH TIME ZONE NOT NULL,
    duration_minutes INTEGER NOT NULL DEFAULT 15,
    
    -- Call status
    status VARCHAR(20) NOT NULL DEFAULT 'scheduled', -- 'scheduled', 'in_progress', 'completed', 'cancelled', 'no_show'
    
    -- User confirmations
    user1_confirmed BOOLEAN DEFAULT false,
    user2_confirmed BOOLEAN DEFAULT false,
    user1_confirmed_at TIMESTAMP WITH TIME ZONE,
    user2_confirmed_at TIMESTAMP WITH TIME ZONE,
    
    -- Call metadata
    call_room_id VARCHAR(255), -- Twilio room ID or similar
    call_started_at TIMESTAMP WITH TIME ZONE,
    call_ended_at TIMESTAMP WITH TIME ZONE,
    actual_duration_minutes INTEGER,
    
    -- Rescheduling info
    original_call_id INTEGER REFERENCES scheduled_calls(id), -- For tracking reschedules
    reschedule_count INTEGER DEFAULT 0,
    
    -- Notifications
    user1_notified BOOLEAN DEFAULT false,
    user2_notified BOOLEAN DEFAULT false,
    reminder_sent BOOLEAN DEFAULT false,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 4. Call Ratings and Feedback
CREATE TABLE IF NOT EXISTS call_ratings (
    id SERIAL PRIMARY KEY,
    call_id INTEGER NOT NULL REFERENCES scheduled_calls(id) ON DELETE CASCADE,
    rater_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rated_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    feedback TEXT,
    categories TEXT[], -- Array of negative categories if applicable
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(call_id, rater_id)
);

-- 5. Call Scheduling Preferences
CREATE TABLE IF NOT EXISTS user_scheduling_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    
    -- Scheduling preferences
    preferred_call_duration INTEGER DEFAULT 15, -- minutes
    max_calls_per_week INTEGER DEFAULT 5,
    min_notice_hours INTEGER DEFAULT 2, -- Minimum notice required
    max_advance_days INTEGER DEFAULT 7, -- How far in advance to schedule
    
    -- Time preferences (in user's local timezone)
    preferred_start_time TIME DEFAULT '18:00:00', -- 6 PM
    preferred_end_time TIME DEFAULT '22:00:00', -- 10 PM
    
    -- Notification preferences
    email_notifications BOOLEAN DEFAULT true,
    push_notifications BOOLEAN DEFAULT true,
    reminder_hours_before INTEGER DEFAULT 1,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 6. Indexes for Performance
CREATE INDEX IF NOT EXISTS idx_user_weekly_availability_user_day ON user_weekly_availability(user_id, day_of_week);
CREATE INDEX IF NOT EXISTS idx_user_availability_overrides_user_date ON user_availability_overrides(user_id, date);
CREATE INDEX IF NOT EXISTS idx_scheduled_calls_users ON scheduled_calls(user1_id, user2_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_calls_start_time ON scheduled_calls(scheduled_start_utc);
CREATE INDEX IF NOT EXISTS idx_scheduled_calls_status ON scheduled_calls(status);
CREATE INDEX IF NOT EXISTS idx_call_ratings_call ON call_ratings(call_id);
CREATE INDEX IF NOT EXISTS idx_call_ratings_rated_user ON call_ratings(rated_user_id);

-- 7. Functions for timezone conversion and availability checking
CREATE OR REPLACE FUNCTION get_user_timezone_offset(user_id_param INTEGER)
RETURNS INTEGER AS $$
BEGIN
    RETURN COALESCE(
        (SELECT timezone_offset FROM user_timezones WHERE user_id = user_id_param),
        0
    );
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION local_to_utc(local_time TIMESTAMP, user_id_param INTEGER)
RETURNS TIMESTAMP WITH TIME ZONE AS $$
BEGIN
    RETURN local_time AT TIME ZONE 'UTC' + (get_user_timezone_offset(user_id_param) || ' minutes')::INTERVAL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION utc_to_local(utc_time TIMESTAMP WITH TIME ZONE, user_id_param INTEGER)
RETURNS TIMESTAMP AS $$
BEGIN
    RETURN (utc_time - (get_user_timezone_offset(user_id_param) || ' minutes')::INTERVAL) AT TIME ZONE 'UTC';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION is_user_available(
    user_id_param INTEGER,
    check_time TIMESTAMP WITH TIME ZONE
)
RETURNS BOOLEAN AS $$
DECLARE
    day_of_week_val INTEGER;
    local_time TIMESTAMP;
    local_date DATE;
    local_time_only TIME;
    has_override BOOLEAN;
    override_available BOOLEAN;
    weekly_available BOOLEAN;
BEGIN
    -- Get user's timezone offset and convert to local time
    local_time := utc_to_local(check_time, user_id_param);
    local_date := local_time::DATE;
    local_time_only := local_time::TIME;
    day_of_week_val := EXTRACT(DOW FROM local_time);
    
    -- Check for specific override first
    SELECT EXISTS(
        SELECT 1 FROM user_availability_overrides 
        WHERE user_id = user_id_param 
        AND date = local_date 
        AND start_time <= local_time_only 
        AND end_time > local_time_only
    ) INTO has_override;
    
    IF has_override THEN
        -- Return override availability
        SELECT is_available INTO override_available
        FROM user_availability_overrides 
        WHERE user_id = user_id_param 
        AND date = local_date 
        AND start_time <= local_time_only 
        AND end_time > local_time_only
        LIMIT 1;
        
        RETURN override_available;
    ELSE
        -- Check weekly availability
        SELECT is_available INTO weekly_available
        FROM user_weekly_availability 
        WHERE user_id = user_id_param 
        AND day_of_week = day_of_week_val
        AND start_time <= local_time_only 
        AND end_time > local_time_only
        LIMIT 1;
        
        RETURN COALESCE(weekly_available, false);
    END IF;
END;
$$ LANGUAGE plpgsql;

-- 8. Triggers for updated_at timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_user_weekly_availability_updated_at
    BEFORE UPDATE ON user_weekly_availability
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_scheduled_calls_updated_at
    BEFORE UPDATE ON scheduled_calls
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_scheduling_preferences_updated_at
    BEFORE UPDATE ON user_scheduling_preferences
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 9. Add timezone column to existing users table if not exists
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'users' AND column_name = 'timezone') THEN
        ALTER TABLE users ADD COLUMN timezone VARCHAR(50) DEFAULT 'UTC';
    END IF;
END $$;

-- 10. Insert default scheduling preferences for existing users
INSERT INTO user_scheduling_preferences (user_id)
SELECT id FROM users
WHERE id NOT IN (SELECT user_id FROM user_scheduling_preferences)
ON CONFLICT DO NOTHING;

-- 11. Insert default timezone records for existing users
INSERT INTO user_timezones (user_id, timezone, timezone_offset)
SELECT id, 'UTC', 0 FROM users
WHERE id NOT IN (SELECT user_id FROM user_timezones)
ON CONFLICT DO NOTHING; 