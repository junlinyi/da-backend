import unittest
from datetime import datetime, timedelta, date
from firebase_admin import firestore, initialize_app, credentials
import os
from pathlib import Path

# Initialize Firebase before any imports that might use Firestore
project_root = Path(__file__).parent.parent
cred_path = os.getenv(
    "FIREBASE_CREDENTIAL_PATH",
    str(project_root / "facedate-6616e-ebf102022977.json")
)
cred = credentials.Certificate(cred_path)
initialize_app(cred)

from app.services.matchmaking import calculate_match_score
from app.models import User

# Add this helper at the top (after imports)
USER_FIELDS = [
    'id', 'email', 'is_active', 'firebase_uid', 'name', 'bio', 'birthdate', 'gender', 'interests', 'location',
    'latitude', 'longitude', 'preferred_gender', 'min_age_preference', 'max_age_preference', 'max_distance_km',
    'last_active', 'profile_completed', 'is_verified', 'profile_image_url', 'additional_image_urls'
]

def filter_user_fields(data):
    return {k: v for k, v in data.items() if k in USER_FIELDS}

class TestMatchmaking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = firestore.client()
        
        # Create test users
        cls.create_test_users()
    
    @classmethod
    def tearDownClass(cls):
        # Clean up test users
        # cls.cleanup_test_users()
        pass
    
    @classmethod
    def create_test_users(cls):
        test_users = [
            {
                'id': 'test_user_1',
                'name': 'Alice',
                'email': 'alice@test.com',
                'birthdate': date(2001, 6, 1),
                'gender': 'female',
                'preferredGender': 'male',
                'interests': ['travel', 'music', 'photography'],
                'location': {
                    'city': 'San Francisco',
                    'state': 'CA'
                },
                'latitude': 37.7749,
                'longitude': -122.4194,
                'minAgePreference': 23,
                'maxAgePreference': 30,
                'profileImageUrl': 'https://example.com/alice.jpg',
                'isVerified': True,
                'strikes': 0
            },
            {
                'id': 'test_user_2',
                'name': 'Bob',
                'email': 'bob@test.com',
                'birthdate': date(1999, 6, 1),
                'gender': 'male',
                'preferredGender': 'female',
                'interests': ['travel', 'music', 'cooking'],
                'location': {
                    'city': 'San Francisco',
                    'state': 'CA'
                },
                'latitude': 37.7833,
                'longitude': -122.4167,
                'minAgePreference': 24,
                'maxAgePreference': 28,
                'profileImageUrl': 'https://example.com/bob.jpg',
                'isVerified': True,
                'strikes': 0
            },
            {
                'id': 'test_user_3',
                'name': 'Charlie',
                'email': 'charlie@test.com',
                'birthdate': date(1991, 6, 1),
                'gender': 'male',
                'preferredGender': 'female',
                'interests': ['gaming', 'technology', 'sports'],
                'location': {
                    'city': 'San Francisco',
                    'state': 'CA'
                },
                'latitude': 37.7750,
                'longitude': -122.4180,
                'minAgePreference': 25,
                'maxAgePreference': 35,
                'profileImageUrl': 'https://example.com/charlie.jpg',
                'isVerified': True,
                'strikes': 0
            }
        ]
        
        # Add users to Firestore
        for user in test_users:
            print(f"Creating user: {user['name']} with ID: {user['id']}")
            cls.db.collection('users').document(user['id']).set(user)
    
    @classmethod
    def cleanup_test_users(cls):
        # Delete test users
        for user_id in ['test_user_1', 'test_user_2', 'test_user_3']:
            cls.db.collection('users').document(user_id).delete()
    
    def test_basic_matching(self):
        """Test basic matching between Alice and Bob"""
        alice_data = self.db.collection('users').document('test_user_1').get().to_dict()
        bob_data = self.db.collection('users').document('test_user_2').get().to_dict()
        alice = User(**filter_user_fields(alice_data))
        bob = User(**filter_user_fields(bob_data))
        score = calculate_match_score(alice, bob)
        self.assertGreater(score, 0, "Match score should be positive for compatible users")
    
    def test_age_mismatch(self):
        """Test matching between Alice and Charlie (age mismatch)"""
        alice_data = self.db.collection('users').document('test_user_1').get().to_dict()
        charlie_data = self.db.collection('users').document('test_user_3').get().to_dict()
        alice = User(**filter_user_fields(alice_data))
        charlie = User(**filter_user_fields(charlie_data))
        score = calculate_match_score(alice, charlie)
        self.assertLess(score, 0.6, "Match score should be lower for age mismatch")
    
    def test_interest_matching(self):
        """Test that shared interests increase match score"""
        alice_data = self.db.collection('users').document('test_user_1').get().to_dict()
        bob_data = self.db.collection('users').document('test_user_2').get().to_dict()
        charlie_data = self.db.collection('users').document('test_user_3').get().to_dict()
        alice = User(**filter_user_fields(alice_data))
        bob = User(**filter_user_fields(bob_data))
        charlie = User(**filter_user_fields(charlie_data))
        alice_bob_score = calculate_match_score(alice, bob)
        alice_charlie_score = calculate_match_score(alice, charlie)
        self.assertGreater(alice_bob_score, alice_charlie_score, "Shared interests should increase match score")
    
    def test_location_matching(self):
        """Test that location proximity affects match score"""
        # Create a user far away (Diana)
        dave_dict = {
            'id': 'test_user_4',
            'email': 'diana@test.com',
            'is_active': True,
            'firebase_uid': 'test_user_4_uid',
            'name': 'Diana',
            'bio': '',
            'birthdate': date(2000, 6, 1),
            'gender': 'female',
            'interests': ['travel', 'music', 'photography'],
            'location': 'New York',
            'latitude': 40.7128,
            'longitude': -74.0060,
            'preferred_gender': 'male',
            'min_age_preference': 23,
            'max_age_preference': 30,
            'max_distance_km': 50,
            'last_active': None,
            'profile_completed': True,
            'is_verified': True,
            'profile_image_url': 'https://example.com/diana.jpg',
            'additional_image_urls': [],
        }
        self.db.collection('users').document('test_user_4').set(dave_dict)

        alice_data = self.db.collection('users').document('test_user_1').get().to_dict()
        bob_data = self.db.collection('users').document('test_user_2').get().to_dict()
        dave_data = self.db.collection('users').document('test_user_4').get().to_dict()
        alice = User(**filter_user_fields(alice_data))
        bob = User(**filter_user_fields(bob_data))
        dave = User(**filter_user_fields(dave_data))
        alice_bob_score = calculate_match_score(alice, bob)
        alice_dave_score = calculate_match_score(alice, dave)
        print(f"Alice/Bob score: {alice_bob_score}")
        print(f"Alice/Dave score: {alice_dave_score}")
        self.assertGreaterEqual(alice_bob_score, alice_dave_score, "Closer location should not decrease match score")

        # Clean up
        self.db.collection('users').document('test_user_4').delete()

if __name__ == '__main__':
    unittest.main() 