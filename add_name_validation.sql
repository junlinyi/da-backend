-- Add name validation and improve data integrity
-- This script adds constraints to prevent invalid names and ensures better data quality

-- 1. Update any existing users with invalid names
UPDATE users 
SET name = NULL 
WHERE name = 'None' OR name = '' OR name IS NULL;

-- 2. Add a check constraint to prevent invalid names in the future
-- Note: We'll add this as a comment since ALTER TABLE ADD CONSTRAINT might fail if data exists
-- ALTER TABLE users ADD CONSTRAINT check_valid_name 
-- CHECK (name IS NOT NULL AND name != '' AND name != 'None' AND length(trim(name)) > 0);

-- 3. Create an index on name for better performance (optional)
CREATE INDEX IF NOT EXISTS idx_users_name ON users(name);

-- 4. Add a function to validate names
CREATE OR REPLACE FUNCTION validate_user_name(name_input TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    -- Check if name is valid
    RETURN name_input IS NOT NULL 
           AND name_input != '' 
           AND name_input != 'None' 
           AND length(trim(name_input)) > 0
           AND name_input ~ '^[a-zA-Z\s]+$';  -- Only letters and spaces
END;
$$ LANGUAGE plpgsql;

-- 5. Show current state
SELECT 
    id, 
    firebase_uid, 
    name, 
    age, 
    gender,
    CASE 
        WHEN name IS NULL OR name = '' OR name = 'None' THEN 'INVALID_NAME'
        WHEN age IS NULL THEN 'MISSING_AGE'
        WHEN gender IS NULL THEN 'MISSING_GENDER'
        WHEN latitude IS NULL OR longitude IS NULL THEN 'MISSING_LOCATION'
        ELSE 'COMPLETE'
    END as profile_status
FROM users 
ORDER BY id; 