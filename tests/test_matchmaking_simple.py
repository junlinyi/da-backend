import unittest
from app.services.matchmaking import calculate_match_score
from app.models import User

class TestMatchmakingSimple(unittest.TestCase):
    
    def test_basic_matching(self):
        """Test basic matching between two compatible users"""
        # Create test users using User model
        alice = User(
            id=1,
            email="alice@test.com",
            name="Alice",
            age=25,
            gender="female",
            preferred_gender="male",
            interests=["travel", "music", "photography"],
            latitude=37.7749,
            longitude=-122.4194,
            min_age_preference=23,
            max_age_preference=30
        )
        
        bob = User(
            id=2,
            email="bob@test.com",
            name="Bob",
            age=27,
            gender="male",
            preferred_gender="female",
            interests=["travel", "music", "cooking"],
            latitude=37.7833,
            longitude=-122.4167,
            min_age_preference=24,
            max_age_preference=28
        )
        
        score = calculate_match_score(alice, bob)
        print(f"Alice-Bob match score: {score}")
        self.assertGreater(score, 0, "Match score should be positive for compatible users")
        self.assertLessEqual(score, 1.0, "Match score should not exceed 1.0")
    
    def test_age_mismatch(self):
        """Test matching between users with age mismatch"""
        alice = User(
            id=1,
            email="alice@test.com",
            name="Alice",
            age=25,
            gender="female",
            preferred_gender="male",
            interests=["travel", "music", "photography"],
            latitude=37.7749,
            longitude=-122.4194,
            min_age_preference=23,
            max_age_preference=30
        )
        
        charlie = User(
            id=3,
            email="charlie@test.com",
            name="Charlie",
            age=45,  # Much older
            gender="male",
            preferred_gender="female",
            interests=["gaming", "technology", "sports"],
            latitude=37.7750,
            longitude=-122.4180,
            min_age_preference=25,
            max_age_preference=35
        )
        
        score = calculate_match_score(alice, charlie)
        print(f"Alice-Charlie match score: {score}")
        self.assertLess(score, 0.6, "Match score should be lower for age mismatch")
    
    def test_interest_matching(self):
        """Test that shared interests increase match score"""
        alice = User(
            id=1,
            email="alice@test.com",
            name="Alice",
            age=25,
            gender="female",
            preferred_gender="male",
            interests=["travel", "music", "photography"],
            latitude=37.7749,
            longitude=-122.4194,
            min_age_preference=23,
            max_age_preference=30
        )
        
        bob = User(
            id=2,
            email="bob@test.com",
            name="Bob",
            age=27,
            gender="male",
            preferred_gender="female",
            interests=["travel", "music", "cooking"],  # 2 shared interests
            latitude=37.7833,
            longitude=-122.4167,
            min_age_preference=24,
            max_age_preference=28
        )
        
        charlie = User(
            id=3,
            email="charlie@test.com",
            name="Charlie",
            age=27,
            gender="male",
            preferred_gender="female",
            interests=["gaming", "technology", "sports"],  # 0 shared interests
            latitude=37.7750,
            longitude=-122.4180,
            min_age_preference=24,
            max_age_preference=28
        )
        
        alice_bob_score = calculate_match_score(alice, bob)
        alice_charlie_score = calculate_match_score(alice, charlie)
        print(f"Alice-Bob score: {alice_bob_score}")
        print(f"Alice-Charlie score: {alice_charlie_score}")
        self.assertGreater(alice_bob_score, alice_charlie_score, "Shared interests should increase match score")
    
    def test_location_matching(self):
        """Test that location proximity affects match score"""
        alice = User(
            id=1,
            email="alice@test.com",
            name="Alice",
            age=25,
            gender="female",
            preferred_gender="male",
            interests=["travel", "music", "photography"],
            latitude=37.7749,
            longitude=-122.4194,
            min_age_preference=23,
            max_age_preference=30
        )
        
        bob = User(
            id=2,
            email="bob@test.com",
            name="Bob",
            age=27,
            gender="male",
            preferred_gender="female",
            interests=["travel", "music", "cooking"],
            latitude=37.7833,
            longitude=-122.4167,  # Close to Alice
            min_age_preference=24,
            max_age_preference=28
        )
        
        diana = User(
            id=4,
            email="diana@test.com",
            name="Diana",
            age=26,
            gender="female",
            preferred_gender="male",
            interests=["travel", "music", "photography"],
            latitude=40.7128,
            longitude=-74.0060,  # Far from Alice (New York)
            min_age_preference=23,
            max_age_preference=30
        )
        
        alice_bob_score = calculate_match_score(alice, bob)
        alice_diana_score = calculate_match_score(alice, diana)
        print(f"Alice-Bob score (close): {alice_bob_score}")
        print(f"Alice-Diana score (far): {alice_diana_score}")
        self.assertGreaterEqual(alice_bob_score, alice_diana_score, "Closer location should not decrease match score")
    
    def test_missing_location_data(self):
        """Test matching when location data is missing"""
        alice = User(
            id=1,
            email="alice@test.com",
            name="Alice",
            age=25,
            gender="female",
            preferred_gender="male",
            interests=["travel", "music", "photography"],
            latitude=None,  # Missing location
            longitude=None,
            min_age_preference=23,
            max_age_preference=30
        )
        
        bob = User(
            id=2,
            email="bob@test.com",
            name="Bob",
            age=27,
            gender="male",
            preferred_gender="female",
            interests=["travel", "music", "cooking"],
            latitude=37.7833,
            longitude=-122.4167,
            min_age_preference=24,
            max_age_preference=28
        )
        
        score = calculate_match_score(alice, bob)
        print(f"Alice-Bob score (missing location): {score}")
        self.assertGreater(score, 0, "Match score should still be positive even with missing location")
        self.assertLess(score, 0.7, "Match score should be lower without location data")

if __name__ == '__main__':
    unittest.main() 