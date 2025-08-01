-- Create complete database schema for the dating app
-- This script creates all tables in the correct dependency order

-- 1. Create users table (base table)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    firebase_uid VARCHAR UNIQUE NOT NULL,
    
    -- Profile Fields
    name VARCHAR,
    bio TEXT,
    age INTEGER,
    gender VARCHAR,
    interests VARCHAR[], -- Array of interests
    location VARCHAR, -- City name
    latitude FLOAT, -- Location coordinates
    longitude FLOAT,
    state VARCHAR, -- State field to match frontend Location struct
    preferred_gender VARCHAR, -- e.g., "male", "female", "any"
    min_age_preference INTEGER DEFAULT 18,
    max_age_preference INTEGER DEFAULT 120,
    max_distance_km INTEGER DEFAULT 32, -- Maximum distance for matches (default 20 miles)
    
    -- Profile Status
    last_active TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    profile_completed BOOLEAN DEFAULT FALSE,
    is_verified BOOLEAN DEFAULT FALSE,
    strikes INTEGER DEFAULT 0, -- Add strikes field to match frontend
    
    -- Profile Images
    profile_image_url VARCHAR,
    additional_image_urls VARCHAR[],
    
    -- Timezone
    timezone VARCHAR DEFAULT 'UTC'
);

-- 2. Create matches table
CREATE TABLE IF NOT EXISTS matches (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    matched_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    match_score FLOAT, -- Score from 0 to 1
    status VARCHAR DEFAULT 'pending', -- pending, accepted, rejected
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Match metadata
    user1_last_active TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    user2_last_active TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    user1_unread_count INTEGER DEFAULT 0,
    user2_unread_count INTEGER DEFAULT 0,
    user1_status VARCHAR DEFAULT 'active', -- active, inactive, blocked
    user2_status VARCHAR DEFAULT 'active',
    
    -- Unique constraint to prevent duplicate matches
    UNIQUE(user_id, matched_user_id)
);

-- 3. Create swipes table
CREATE TABLE IF NOT EXISTS swipes (
    id SERIAL PRIMARY KEY,
    swiper_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    swiped_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    liked BOOLEAN DEFAULT FALSE, -- True = like, False = pass
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    match_score FLOAT -- Score from 0 to 1
);

-- 4. Create conversations table
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    user1_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user2_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_message TEXT,
    last_message_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    user1_unread_count INTEGER DEFAULT 0,
    user2_unread_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE(user1_id, user2_id)
);

-- 5. Create messages table
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    message_type VARCHAR(20) DEFAULT 'text', -- text, image, video, audio
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_read BOOLEAN DEFAULT FALSE,
    firebase_id VARCHAR UNIQUE -- Firebase message ID for syncing
);

-- 6. Create user_weekly_availability table
CREATE TABLE IF NOT EXISTS user_weekly_availability (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day_of_week INTEGER NOT NULL, -- 0=Sunday, 6=Saturday
    start_time TIME NOT NULL, -- Local time in user's timezone
    end_time TIME NOT NULL, -- Local time in user's timezone
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Unique constraint
    UNIQUE(user_id, day_of_week, start_time, end_time)
);

-- 7. Create user_availability_overrides table
CREATE TABLE IF NOT EXISTS user_availability_overrides (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date DATE NOT NULL, -- Specific date
    start_time TIME NOT NULL, -- Local time in user's timezone
    end_time TIME NOT NULL, -- Local time in user's timezone
    reason VARCHAR(255), -- Optional reason for override
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Unique constraint
    UNIQUE(user_id, date, start_time, end_time)
);

-- 8. Create user_timezones table
CREATE TABLE IF NOT EXISTS user_timezones (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    timezone VARCHAR(50) NOT NULL DEFAULT 'UTC', -- e.g., 'America/New_York'
    timezone_offset INTEGER NOT NULL DEFAULT 0, -- Offset in minutes from UTC
    dst_enabled BOOLEAN NOT NULL DEFAULT FALSE, -- Daylight saving time enabled
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 9. Create user_scheduling_preferences table
CREATE TABLE IF NOT EXISTS user_scheduling_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    
    -- Scheduling preferences (fixed 15-minute calls)
    max_calls_per_week INTEGER DEFAULT 5,
    min_notice_hours INTEGER DEFAULT 2, -- Minimum notice required
    max_advance_days INTEGER DEFAULT 7, -- How far in advance to schedule
    
    -- Time preferences (in user's local timezone)
    preferred_start_time TIME DEFAULT '18:00:00', -- 6 PM
    preferred_end_time TIME DEFAULT '22:00:00', -- 10 PM
    
    -- Notification preferences
    email_notifications BOOLEAN DEFAULT TRUE,
    push_notifications BOOLEAN DEFAULT TRUE,
    reminder_hours_before INTEGER DEFAULT 1,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 10. Create scheduled_calls table
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
    user1_confirmed BOOLEAN DEFAULT FALSE,
    user2_confirmed BOOLEAN DEFAULT FALSE,
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
    user1_notified BOOLEAN DEFAULT FALSE,
    user2_notified BOOLEAN DEFAULT FALSE,
    reminder_sent BOOLEAN DEFAULT FALSE,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 11. Create call_ratings table
CREATE TABLE IF NOT EXISTS call_ratings (
    id SERIAL PRIMARY KEY,
    call_id INTEGER NOT NULL REFERENCES scheduled_calls(id) ON DELETE CASCADE,
    rater_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rated_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    rating INTEGER NOT NULL, -- 1-5
    feedback TEXT,
    categories VARCHAR[], -- Array of negative categories if applicable
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_users_firebase_uid ON users(firebase_uid);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_location ON users(location);
CREATE INDEX IF NOT EXISTS idx_users_age ON users(age);
CREATE INDEX IF NOT EXISTS idx_users_gender ON users(gender);

CREATE INDEX IF NOT EXISTS idx_matches_user_id ON matches(user_id);
CREATE INDEX IF NOT EXISTS idx_matches_matched_user_id ON matches(matched_user_id);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);

CREATE INDEX IF NOT EXISTS idx_swipes_swiper_id ON swipes(swiper_id);
CREATE INDEX IF NOT EXISTS idx_swipes_swiped_id ON swipes(swiped_id);
CREATE INDEX IF NOT EXISTS idx_swipes_timestamp ON swipes(timestamp);

CREATE INDEX IF NOT EXISTS idx_conversations_user1 ON conversations(user1_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user2 ON conversations(user2_id);
CREATE INDEX IF NOT EXISTS idx_conversations_last_message ON conversations(last_message_at DESC);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_id);
CREATE INDEX IF NOT EXISTS idx_messages_firebase_id ON messages(firebase_id);

CREATE INDEX IF NOT EXISTS idx_weekly_availability_user ON user_weekly_availability(user_id);
CREATE INDEX IF NOT EXISTS idx_weekly_availability_day ON user_weekly_availability(day_of_week);

CREATE INDEX IF NOT EXISTS idx_availability_overrides_user ON user_availability_overrides(user_id);
CREATE INDEX IF NOT EXISTS idx_availability_overrides_date ON user_availability_overrides(date);

CREATE INDEX IF NOT EXISTS idx_scheduled_calls_match ON scheduled_calls(match_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_calls_user1 ON scheduled_calls(user1_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_calls_user2 ON scheduled_calls(user2_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_calls_start ON scheduled_calls(scheduled_start_utc);
CREATE INDEX IF NOT EXISTS idx_scheduled_calls_status ON scheduled_calls(status);

CREATE INDEX IF NOT EXISTS idx_call_ratings_call ON call_ratings(call_id);
CREATE INDEX IF NOT EXISTS idx_call_ratings_rater ON call_ratings(rater_id);
CREATE INDEX IF NOT EXISTS idx_call_ratings_rated ON call_ratings(rated_user_id);

-- Add a function to automatically create conversations when matches are made
CREATE OR REPLACE FUNCTION create_conversation_for_match()
RETURNS TRIGGER AS $$
BEGIN
    -- When a match is created, create a conversation
    INSERT INTO conversations (user1_id, user2_id)
    VALUES (NEW.user_id, NEW.matched_user_id)
    ON CONFLICT (user1_id, user2_id) DO NOTHING;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to automatically create conversations for new matches
DROP TRIGGER IF EXISTS trigger_create_conversation ON matches;
CREATE TRIGGER trigger_create_conversation
    AFTER INSERT ON matches
    FOR EACH ROW
    EXECUTE FUNCTION create_conversation_for_match();

-- Show all created tables
SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name IN (
    'users', 'matches', 'swipes', 'conversations', 'messages',
    'user_weekly_availability', 'user_availability_overrides',
    'user_timezones', 'user_scheduling_preferences',
    'scheduled_calls', 'call_ratings'
)
ORDER BY table_name, ordinal_position; 