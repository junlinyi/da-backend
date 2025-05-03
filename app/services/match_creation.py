# app/services/match_creation.py

from firebase_admin import firestore

def create_match_in_firestore(user1_uid: str, user2_uid: str):
    db = firestore.client()

    # Create a new match document with a generated ID
    match_ref = db.collection("matches").document()

    match_ref.set({
        "users": [user1_uid, user2_uid],
        "lastMessage": "",
        "lastUpdated": firestore.SERVER_TIMESTAMP
    })

    print(f"Match created in Firestore: {match_ref.id}")
    return match_ref.id  # Optional: return match ID
