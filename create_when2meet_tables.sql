-- When2Meet Style Availability Tables
-- These tables support grid-based availability selection (7 days × 24 hours × 2 slots per hour)

-- Default availability (weekly recurring schedule)
CREATE TABLE IF NOT EXISTS user_default_availability (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day_of_week INTEGER NOT NULL CHECK (day_of_week >= 0 AND day_of_week <= 6), -- 0-6 (Sunday-Saturday)
    hour INTEGER NOT NULL CHECK (hour >= 0 AND hour <= 23), -- 0-23
    minute INTEGER NOT NULL CHECK (minute IN (0, 30)), -- 0 or 30 (30-minute slots)
    is_available BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Ensure unique combination of user, day, hour, minute
    UNIQUE(user_id, day_of_week, hour, minute)
);

-- Override availability (specific week modifications)
CREATE TABLE IF NOT EXISTS user_override_availability (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    week_start_date DATE NOT NULL, -- YYYY-MM-DD format
    day_of_week INTEGER NOT NULL CHECK (day_of_week >= 0 AND day_of_week <= 6), -- 0-6 (Sunday-Saturday)
    hour INTEGER NOT NULL CHECK (hour >= 0 AND hour <= 23), -- 0-23
    minute INTEGER NOT NULL CHECK (minute IN (0, 30)), -- 0 or 30 (30-minute slots)
    is_available BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Ensure unique combination of user, week, day, hour, minute
    UNIQUE(user_id, week_start_date, day_of_week, hour, minute)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_user_default_availability_user_id ON user_default_availability(user_id);
CREATE INDEX IF NOT EXISTS idx_user_default_availability_day_hour ON user_default_availability(day_of_week, hour);
CREATE INDEX IF NOT EXISTS idx_user_override_availability_user_id ON user_override_availability(user_id);
CREATE INDEX IF NOT EXISTS idx_user_override_availability_week_date ON user_override_availability(week_start_date);
CREATE INDEX IF NOT EXISTS idx_user_override_availability_user_week ON user_override_availability(user_id, week_start_date);

-- Function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers to automatically update updated_at
CREATE TRIGGER update_user_default_availability_updated_at 
    BEFORE UPDATE ON user_default_availability 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_override_availability_updated_at 
    BEFORE UPDATE ON user_override_availability 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Function to get effective availability for a specific week
-- This combines default availability with any overrides
CREATE OR REPLACE FUNCTION get_effective_availability(
    p_user_id INTEGER,
    p_week_start_date DATE
) RETURNS TABLE(
    day_of_week INTEGER,
    hour INTEGER,
    minute INTEGER,
    is_available BOOLEAN,
    is_override BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    WITH all_slots AS (
        -- Generate all possible time slots for the week (7 days × 24 hours × 2 slots)
        SELECT 
            d.day_of_week,
            h.hour,
            m.minute
        FROM generate_series(0, 6) AS d(day_of_week)
        CROSS JOIN generate_series(0, 23) AS h(hour)
        CROSS JOIN (VALUES (0), (30)) AS m(minute)
    ),
    default_slots AS (
        -- Get default availability
        SELECT 
            day_of_week,
            hour,
            minute,
            is_available,
            false as is_override
        FROM user_default_availability
        WHERE user_id = p_user_id
    ),
    override_slots AS (
        -- Get override availability for the specific week
        SELECT 
            day_of_week,
            hour,
            minute,
            is_available,
            true as is_override
        FROM user_override_availability
        WHERE user_id = p_user_id AND week_start_date = p_week_start_date
    )
    SELECT 
        s.day_of_week,
        s.hour,
        s.minute,
        COALESCE(o.is_available, d.is_available, false) as is_available,
        COALESCE(o.is_override, false) as is_override
    FROM all_slots s
    LEFT JOIN default_slots d ON s.day_of_week = d.day_of_week AND s.hour = d.hour AND s.minute = d.minute
    LEFT JOIN override_slots o ON s.day_of_week = o.day_of_week AND s.hour = o.hour AND s.minute = o.minute
    ORDER BY s.day_of_week, s.hour, s.minute;
END;
$$ LANGUAGE plpgsql;

-- Function to check if a user is available at a specific time
CREATE OR REPLACE FUNCTION check_user_availability(
    p_user_id INTEGER,
    p_target_date DATE,
    p_target_hour INTEGER,
    p_target_minute INTEGER
) RETURNS BOOLEAN AS $$
DECLARE
    day_of_week INTEGER;
    week_start_date DATE;
    is_available BOOLEAN;
BEGIN
    -- Get day of week (0-6, where 0 is Sunday)
    day_of_week := EXTRACT(DOW FROM p_target_date);
    
    -- Get week start date (Sunday of the target week)
    week_start_date := p_target_date - (day_of_week || ' days')::INTERVAL;
    
    -- Check for override first, then default
    SELECT COALESCE(
        (SELECT is_available FROM user_override_availability 
         WHERE user_id = p_user_id 
         AND week_start_date = week_start_date
         AND day_of_week = day_of_week
         AND hour = p_target_hour
         AND minute = p_target_minute),
        (SELECT is_available FROM user_default_availability 
         WHERE user_id = p_user_id 
         AND day_of_week = day_of_week
         AND hour = p_target_hour
         AND minute = p_target_minute),
        false
    ) INTO is_available;
    
    RETURN is_available;
END;
$$ LANGUAGE plpgsql;

-- Comments
COMMENT ON TABLE user_default_availability IS 'Stores user''s default weekly availability in 30-minute slots (When2Meet style)';
COMMENT ON TABLE user_override_availability IS 'Stores user''s override availability for specific weeks (When2Meet style)';
COMMENT ON FUNCTION get_effective_availability IS 'Returns effective availability combining default and override for a specific week';
COMMENT ON FUNCTION check_user_availability IS 'Checks if a user is available at a specific date/time'; 