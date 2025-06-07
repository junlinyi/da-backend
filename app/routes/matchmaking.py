from flask import Blueprint, jsonify, request
from firebase_admin import firestore
from datetime import datetime, timedelta
from typing import List, Dict, Any
from geopy.distance import geodesic
from ..services.matchmaking import calculate_match_score

matchmaking_bp = Blueprint('matchmaking', __name__)
db = firestore.client()

@matchmaking_bp.route('/api/matchmaking/potential-matches', methods=['GET'])
def get_potential_matches():
    try:
        user_id = request.args.get('userId')
        if not user_id:
            return jsonify({'error': 'User ID is required'}), 400

        # Get user's preferences and profile
        user_doc = db.collection('users').document(user_id).get()
        if not user_doc.exists:
            return jsonify({'error': 'User not found'}), 404

        user_data = user_doc.to_dict()
        
        # Get user's swipes for today
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        swipes = db.collection('swipes')\
            .where('swiperId', '==', user_id)\
            .where('timestamp', '>=', today)\
            .get()
        
        swiped_ids = {doc.to_dict()['swipedId'] for doc in swipes}

        # Get potential matches based on basic criteria
        query = db.collection('users')\
            .where('gender', '==', user_data.get('preferredGender'))\
            .where('id', '!=', user_id)\
            .limit(50)  # Get more than needed to filter by score

        potential_matches = query.get()
        
        # Calculate match scores and filter
        scored_matches = []
        for match in potential_matches:
            match_data = match.to_dict()
            match_id = match.id
            
            # Skip already swiped users
            if match_id in swiped_ids:
                continue
                
            # Calculate match score
            score = calculate_match_score(
                user1_data=user_data,
                user2_data=match_data,
                user1_id=user_id,
                user2_id=match_id
            )
            
            if score > 0:  # Only include matches with positive scores
                scored_matches.append({
                    'id': match_id,
                    'name': match_data.get('name', ''),
                    'age': match_data.get('age'),
                    'bio': match_data.get('bio', ''),
                    'gender': match_data.get('gender'),
                    'interests': match_data.get('interests', []),
                    'profileImageUrl': match_data.get('profileImageUrl'),
                    'location': match_data.get('location'),
                    'matchScore': score
                })

        # Sort by match score and take top 7
        scored_matches.sort(key=lambda x: x['matchScore'], reverse=True)
        top_matches = scored_matches[:7]

        return jsonify({
            'matches': top_matches,
            'remainingSwipes': 7 - len(swiped_ids)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500 