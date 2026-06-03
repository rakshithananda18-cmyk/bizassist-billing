import os
import sys

# Set test environment database to a temporary file and mock api keys
os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist_claude.db"
os.environ["CLAUDE_API_KEY"] = "mock_claude_api_key"

# Clean up any leftover databases
for db_path in ["test_bizassist_claude.db", "backend/test_bizassist_claude.db"]:
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

# Ensure backend folder is in path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main_claude import app

client = TestClient(app)


def test_home():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "BizAssist AI Claude server running"}


def test_auth_flow_claude():
    # Register a test pharmacy business
    signup_response = client.post("/signup", json={
        "username": "pharmacy_claude",
        "password": "ClaudePassword123",
        "business_name": "Claude Pharmacy Lab"
    })
    assert signup_response.status_code == 200
    assert signup_response.json()["username"] == "pharmacy_claude"

    # Log in to fetch JWT
    login_response = client.post("/login", json={
        "username": "pharmacy_claude",
        "password": "ClaudePassword123"
    })
    assert login_response.status_code == 200
    token_data = login_response.json()
    assert "token" in token_data


@patch("main_claude.client.messages.create")
def test_ask_ai_flow_claude(mock_messages_create):
    # Mock text block
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "Mocked Claude response about sales advice."
    
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_messages_create.return_value = mock_response

    # Register/Login
    client.post("/signup", json={
        "username": "claude_user",
        "password": "ClaudePassword123",
        "business_name": "Claude Retail Store"
    })
    login_response = client.post("/login", json={
        "username": "claude_user",
        "password": "ClaudePassword123"
    })
    token = login_response.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # DIRECT path ask (cached query or direct routing)
    response = client.post("/ask", json={"message": "how many invoices"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["source"] == "db"

    # AI path ask (Claude LLM)
    response = client.post("/ask", json={"message": "how can I increase overall customer satisfaction?"}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "ai"
    assert "Mocked Claude response" in data["response"]


@patch("main_claude.client.messages.create")
def test_ask_ai_tool_calling_flow_claude(mock_messages_create):
    # First completion yields tool call block
    mock_tool_block = MagicMock()
    mock_tool_block.type = "tool_use"
    mock_tool_block.id = "call_top_cust"
    mock_tool_block.name = "rank_top_customers"
    mock_tool_block.input = {"limit": 3}
    
    mock_response1 = MagicMock()
    mock_response1.content = [mock_tool_block]
    
    # Second completion yields final text summary
    mock_text_block = MagicMock()
    mock_text_block.type = "text"
    mock_text_block.text = "Based on database lookup, Claude finds that Medicare is the top customer."
    
    mock_response2 = MagicMock()
    mock_response2.content = [mock_text_block]
    
    # Setup mock sequences
    mock_messages_create.side_effect = [mock_response1, mock_response2]

    # Login
    login_response = client.post("/login", json={
        "username": "claude_user",
        "password": "ClaudePassword123"
    })
    token = login_response.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post("/ask", json={"message": "who are my best clients?"}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "ai"
    assert "Medicare" in data["response"]
