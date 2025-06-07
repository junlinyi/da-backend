import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import User
from app.database import Base

# Create database engine
DATABASE_URL = "postgresql://dating_user:@localhost:5432/dating_app"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def create_test_users():
    db = SessionLocal()
    
    # Test users data
    test_users = [
        {
            'email': 'alice@test.com',
            'firebase_uid': 'test_user_1',
            'name': 'Alice',
            'age': 25,
            'gender': 'female',
            'preferred_gender': 'male',
            'interests': ['travel', 'music', 'photography'],
            'location': 'San Francisco',
            'latitude': 37.7749,
            'longitude': -122.4194,
            'min_age_preference': 23,
            'max_age_preference': 30,
            'profile_image_url': 'https://example.com/alice.jpg',
            'is_verified': True
        },
        {
            'email': 'bob@test.com',
            'firebase_uid': 'test_user_2',
            'name': 'Bob',
            'age': 27,
            'gender': 'male',
            'preferred_gender': 'female',
            'interests': ['travel', 'music', 'cooking'],
            'location': 'San Francisco',
            'latitude': 37.7833,
            'longitude': -122.4167,
            'min_age_preference': 24,
            'max_age_preference': 28,
            'profile_image_url': 'https://example.com/bob.jpg',
            'is_verified': True
        },
        {
            'email': 'charlie@test.com',
            'firebase_uid': 'test_user_3',
            'name': 'Charlie',
            'age': 35,
            'gender': 'male',
            'preferred_gender': 'female',
            'interests': ['gaming', 'technology', 'sports'],
            'location': 'San Francisco',
            'latitude': 37.7750,
            'longitude': -122.4180,
            'min_age_preference': 25,
            'max_age_preference': 35,
            'profile_image_url': 'https://example.com/charlie.jpg',
            'is_verified': True
        },
        {
            'email': 'diana@test.com',
            'firebase_uid': 'test_user_4',
            'name': 'Diana',
            'age': 26,
            'gender': 'female',
            'preferred_gender': 'male',
            'interests': ['travel', 'music', 'photography'],
            'location': 'New York',
            'latitude': 40.7128,
            'longitude': -74.0060,
            'min_age_preference': 23,
            'max_age_preference': 30,
            'profile_image_url': 'https://example.com/diana.jpg',
            'is_verified': True
        }
    ]
    
    try:
        # Create users
        for user_data in test_users:
            user = User(**user_data)
            db.add(user)
        
        # Commit changes
        db.commit()
        print("Test users created successfully!")
        
    except Exception as e:
        db.rollback()
        print(f"Error creating test users: {e}")
    
    finally:
        db.close()

if __name__ == "__main__":
    create_test_users() 