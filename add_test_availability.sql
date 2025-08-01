-- Add test weekly availability data for users 1 and 2

-- User 1 (Juan Baek) - Available Monday and Wednesday evenings
INSERT INTO user_weekly_availability (user_id, day_of_week, start_time, end_time) VALUES
(1, 1, '18:00:00', '20:00:00'),  -- Monday 6-8 PM
(1, 3, '19:00:00', '21:00:00');  -- Wednesday 7-9 PM

-- User 2 (Lena Huynh) - Available Monday and Tuesday evenings  
INSERT INTO user_weekly_availability (user_id, day_of_week, start_time, end_time) VALUES
(2, 1, '17:00:00', '19:00:00'),  -- Monday 5-7 PM
(2, 2, '18:00:00', '20:00:00');  -- Tuesday 6-8 PM

-- Add some overrides for specific dates
INSERT INTO user_availability_overrides (user_id, date, start_time, end_time, reason) VALUES
(1, '2025-07-07', '19:00:00', '21:00:00', 'Special availability'),  -- Monday July 7
(2, '2025-07-07', '18:00:00', '20:00:00', 'Special availability');  -- Monday July 7

-- Create a match between users 1 and 2 (if it doesn't exist)
INSERT INTO matches (user_id, matched_user_id, status) VALUES
(1, 2, 'pending')
ON CONFLICT (user_id, matched_user_id) DO NOTHING;

-- Show what we added
SELECT 'Test data added successfully' as result; 