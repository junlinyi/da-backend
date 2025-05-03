from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_register():
    response = client.post("/register", json={"email": "testuser@example.com", "password": "testpassword"})
    assert response.status_code == 201

def test_login():
    response = client.post("/login", data={"username": "testuser@example.com", "password": "testpassword"})
    assert response.status_code == 200
    assert "access_token" in response.json()
