-- Migration script to convert interests column from character varying to character varying[]
-- This fixes the matchmaking algorithm interest calculation

-- Step 1: Create a backup of current interests data
CREATE TEMP TABLE interests_backup AS 
SELECT id, interests FROM users WHERE interests IS NOT NULL AND interests != '';

-- Step 2: Add a new interests_array column
ALTER TABLE users ADD COLUMN interests_array character varying[];

-- Step 3: Convert existing string data to proper arrays
-- Handle different formats of existing data
UPDATE users 
SET interests_array = CASE 
    -- If it's already in array format like {Travel,Food}
    WHEN interests LIKE '{%}' THEN 
        string_to_array(trim(both '{}' from interests), ',')
    -- If it's a single value without braces
    WHEN interests IS NOT NULL AND interests != '' THEN 
        ARRAY[interests]
    -- If it's empty or null
    ELSE NULL
END
WHERE interests IS NOT NULL;

-- Step 4: Drop the old interests column
ALTER TABLE users DROP COLUMN interests;

-- Step 5: Rename the new column to interests
ALTER TABLE users RENAME COLUMN interests_array TO interests;

-- Step 6: Verify the migration
SELECT id, name, interests, pg_typeof(interests) as interest_type 
FROM users 
WHERE interests IS NOT NULL 
ORDER BY id;

-- Step 7: Test the array operations
SELECT id, name, interests, array_length(interests, 1) as interest_count
FROM users 
WHERE interests IS NOT NULL 
ORDER BY id; 