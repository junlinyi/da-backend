from flask import Flask
from firebase_admin import credentials, initialize_app

def create_app():
    app = Flask(__name__)
    
    # Initialize Firebase
    cred = credentials.Certificate("path/to/serviceAccountKey.json")
    initialize_app(cred)
    
    # Register blueprints
    from .routes.matchmaking import matchmaking_bp
    app.register_blueprint(matchmaking_bp)
    
    return app
