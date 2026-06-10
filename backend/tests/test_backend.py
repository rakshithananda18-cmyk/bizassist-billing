import os
import sys

# Set test environment database to a temporary file and mock api keys
os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

# Clean up any leftover databases from previous runs before importing main_groq
for db_path in ["test_bizassist.db", "backend/test_bizassist.db"]:
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
from main_groq import app
from services.query_router import classify
from services.auth import hash_password, verify_password

client = TestClient(app)

@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db():
    yield
    # Clean up test database files at session end
    for db_path in ["test_bizassist.db", "backend/test_bizassist.db"]:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.fixture(autouse=True)
def clear_rate_limit_windows():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()

def test_query_classification():
    # Direct database queries
    assert classify("how many invoices")[0] == "DIRECT"
    assert classify("total revenue")[0] == "DIRECT"
    assert classify("who is overdue")[0] == "DIRECT"
    assert classify("low stock")[0] == "DIRECT"
    assert classify("medicines expiring")[0] == "DIRECT"   # expiry pattern still catches it
    assert classify("dashboard overview")[0] == "DIRECT"

    # Conversational short-circuit — must NOT hit DB or AI
    assert classify("okay")[0] == "CONVERSATIONAL"
    assert classify("thanks")[0] == "CONVERSATIONAL"
    assert classify("yes")[0] == "CONVERSATIONAL"
    assert classify("hi")[0] == "CONVERSATIONAL"
    assert classify("cool")[0] == "CONVERSATIONAL"

    # Top debtors — distinct from top customers
    route, key = classify("top debtors")
    assert route == "DIRECT"
    assert key == "top_debtors"

    route, key = classify("who owes me the most")
    assert route == "DIRECT"
    assert key == "top_debtors"

    # AI reasoning queries
    assert classify("what business strategy should I adopt?")[0] == "AI_COMPLEX"
    assert classify("how can I increase my sales?")[0] == "AI_COMPLEX"
    assert classify("who is my most reliable supplier?")[0] == "AI_SIMPLE"

def test_password_hashing():
    pwd = "mysecretpassword"
    hashed = hash_password(pwd)
    assert verify_password(pwd, hashed) is True
    assert verify_password("wrongpassword", hashed) is False

def test_unauthenticated_access():
    # Protected endpoints should return 401 Unauthorized
    protected_endpoints = [
        "/admin/businesses",
        "/dashboard-summary",
        "/database",
        "/top-customers",
        "/payments",
        "/clients",
        "/uploads"
    ]
    for endpoint in protected_endpoints:
        response = client.get(endpoint)
        assert response.status_code == 401

def test_auth_flow():
    # Login with seeded test users (see main_groq.py run_migrations_and_seed)
    response = client.post("/login", json={
        "username": "pharmacy",
        "password": "pharmacy123"
    })
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert data["username"] == "pharmacy"
    assert data["business_name"] == "MediCare Pharmacy"

    # Invalid login
    response = client.post("/login", json={
        "username": "pharmacy",
        "password": "wrongpassword"
    })
    assert response.status_code == 401

    # Signup flow
    response = client.post("/signup", json={
        "username": "newuser",
        "password": "Newpassword123",
        "business_name": "New Retail Shop"
    })
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert data["username"] == "newuser"
    assert data["business_name"] == "New Retail Shop"

    # Duplicate username signup
    response = client.post("/signup", json={
        "username": "newuser",
        "password": "Anotherpassword123",
        "business_name": "Another Shop"
    })
    assert response.status_code == 400

def test_authorized_endpoints():
    # First, authenticate to get a token
    login_response = client.post("/login", json={
        "username": "pharmacy",
        "password": "pharmacy123"
    })
    token = login_response.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Verify protected endpoints return 200
    response = client.get("/dashboard-summary", headers=headers)
    assert response.status_code == 200
    summary = response.json()
    assert "total_revenue" in summary
    assert "invoice_count" in summary
    assert "inventory_count" in summary

    response = client.get("/database", headers=headers)
    assert response.status_code == 200
    db_data = response.json()
    assert "invoices" in db_data
    assert "inventory" in db_data
    assert "uploads" in db_data

    response = client.get("/top-customers", headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)

    response = client.get("/payments", headers=headers)
    assert response.status_code == 200
    payments = response.json()
    assert "payments" in payments
    assert "invoice_dues" in payments

    response = client.get("/clients", headers=headers)
    assert response.status_code == 200
    clients_data = response.json()
    assert "clients" in clients_data

@patch("routes.ask._client.chat.completions.create")
def test_ask_ai_flow(mock_chat_create):
    # Mock LLM API response
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="Mocked LLM answer about sales strategy."))
    ]
    mock_chat_create.return_value = mock_response

    # Login to get valid session
    login_response = client.post("/login", json={
        "username": "pharmacy",
        "password": "pharmacy123"
    })
    token = login_response.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # DIRECT path ask
    response = client.post("/ask", json={"message": "how many invoices"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["source"] == "db"

    # AI path ask
    response = client.post("/ask", json={"message": "who is my most reliable supplier?"}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "ai"
    assert "Mocked LLM answer" in data["response"]

@patch("routes.ask._client.chat.completions.create")
def test_ask_ai_tool_calling_flow(mock_chat_create):
    # Flush query cache so the previous test's cached response for the same
    # query + user doesn't short-circuit Layer 2 before the mocks fire.
    from services.context_cache import invalidate
    invalidate()

    # We mock two completions:
    # First completion returns a tool call to 'get_top_customers'.
    # Second completion returns the final response summarizing the tool output.
    mock_msg1 = MagicMock()
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_123"
    mock_tool_call.function.name = "rank_top_customers"
    mock_tool_call.function.arguments = '{"limit": 3}'
    mock_msg1.tool_calls = [mock_tool_call]
    mock_msg1.content = None
    
    mock_response1 = MagicMock()
    mock_response1.choices = [MagicMock(message=mock_msg1)]
    
    mock_msg2 = MagicMock()
    mock_msg2.tool_calls = None
    mock_msg2.content = "Based on tool output, top customer is MediCare Pharmacy."
    
    mock_response2 = MagicMock()
    mock_response2.choices = [MagicMock(message=mock_msg2)]
    
    mock_chat_create.side_effect = [mock_response1, mock_response2]

    # Login to get valid session
    login_response = client.post("/login", json={
        "username": "pharmacy",
        "password": "pharmacy123"
    })
    token = login_response.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post("/ask", json={"message": "who is my most reliable supplier?"}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "ai"
    assert "MediCare Pharmacy" in data["response"]

def test_dynamic_numeric_queries_bypass_direct():
    from services.query_router import classify
    # "expiring soon" has no digits -> DIRECT
    route, key = classify("expiring soon")
    assert route == "DIRECT"
    assert key == "expiring_soon"

    # "expiring in 15 days" has digits -> AI_SIMPLE
    route, key = classify("expiring in 15 days")
    assert route == "AI_SIMPLE"
    assert key is None

    # "top customers" has no digits -> DIRECT
    route, key = classify("top customers")
    assert route == "DIRECT"
    assert key == "top_customers"

    # "top 3 customers" has digits -> AI_SIMPLE
    route, key = classify("top 3 customers")
    assert route == "AI_SIMPLE"
    assert key is None

    # Standard dashboard aging bar click -> DIRECT (overdue_range_detail)
    route, key = classify("Tell me about overdue payments in range 61-90 days")
    assert route == "DIRECT"
    assert key == "overdue_range_detail"

    # Standard dashboard revenue month click -> DIRECT (revenue_month_detail)
    route, key = classify("Tell me about revenue in Oct 2025")
    assert route == "DIRECT"
    assert key == "revenue_month_detail"

    # Support 2-digit years in dashboard monthly revenue queries
    route, key = classify("Tell me about revenue in Apr 26")
    assert route == "DIRECT"
    assert key == "revenue_month_detail"

    # Dynamic query with default expiring_soon days -> DIRECT (expiring_soon)
    route, key = classify("Which products are expiring in the next 30 days?")
    assert route == "DIRECT"
    assert key == "expiring_soon"

    # Dynamic query with default top_customers count -> DIRECT (top_customers)
    route, key = classify("Who are my top 5 customers by revenue?")
    assert route == "DIRECT"
    assert key == "top_customers"

    # Test reasoning/strategy keyword bypass to AI path
    route, key = classify("Develop a promotional strategy to clear expiring products and minimize waste.")
    assert route == "AI_COMPLEX"
    assert key is None

    route, key = classify("Implement a stock management system to track low-stock products and optimize reorder times.")
    assert route == "AI_COMPLEX"
    assert key is None

    # Test "Analyze/analyse" spelling variations for uploaded files
    route, key = classify("Analyze the uploaded file")
    assert route == "AI_COMPLEX"
    assert key is None

    route, key = classify("analyse the uploaded dataset")
    assert route == "AI_COMPLEX"
    assert key is None


def test_chat_history_endpoints():
    # Login to get valid token
    login_response = client.post("/login", json={
        "username": "pharmacy",
        "password": "pharmacy123"
    })
    token = login_response.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Clear history to start with clean state
    client.delete("/chat/history", headers=headers)
    
    # Check sessions is empty
    response = client.get("/chat/sessions", headers=headers)
    assert response.status_code == 200
    assert response.json() == []

    # Send a DIRECT path query which logs user and assistant message automatically
    response = client.post("/ask", json={"message": "how many invoices"}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    session_id = data["session_id"]
    assert "session_title" in data

    # Check sessions list contains the new session
    response = client.get("/chat/sessions", headers=headers)
    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == session_id

    # Retrieve history for this session specifically
    response = client.get(f"/chat/history?session_id={session_id}", headers=headers)
    assert response.status_code == 200
    history = response.json()
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "how many invoices"
    assert history[1]["role"] == "assistant"

    # Send a query on a NEW session_id explicitly
    new_session_id = "test-session-abc"
    response = client.post("/ask", json={"message": "low stock", "session_id": new_session_id}, headers=headers)
    assert response.status_code == 200
    assert response.json()["session_id"] == new_session_id

    # Verify sessions list now has 2 sessions
    response = client.get("/chat/sessions", headers=headers)
    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 2
    
    # Clear only the second session
    response = client.delete(f"/chat/history?session_id={new_session_id}", headers=headers)
    assert response.status_code == 200
    
    # Verify sessions list is back to 1
    response = client.get("/chat/sessions", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 1

    # Verify we can clear remaining conversations
    response = client.delete("/chat/history", headers=headers)
    assert response.status_code == 200
    response = client.get("/chat/sessions", headers=headers)
    assert response.json() == []


def test_admin_endpoints():
    # 1. Login as admin
    admin_login = client.post("/login", json={
        "username": "admin",
        "password": "admin123"
    })
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 2. Login as enterprise user
    user_login = client.post("/login", json={
        "username": "pharmacy",
        "password": "pharmacy123"
    })
    assert user_login.status_code == 200
    user_token = user_login.json()["token"]
    user_id = user_login.json()["id"]
    user_headers = {"Authorization": f"Bearer {user_token}"}

    # 2.1 Test 403 Forbidden on create and update user for non-admin
    resp = client.post("/admin/create-user", json={
        "username": "new_biz",
        "password": "new_password",
        "business_name": "New Business"
    }, headers=user_headers)
    assert resp.status_code == 403

    resp = client.put(f"/admin/update-user/{user_id}", json={
        "business_name": "Updated Business"
    }, headers=user_headers)
    assert resp.status_code == 403

    # 2.2 Test Create User as Admin
    create_resp = client.post("/admin/create-user", json={
        "username": "new_biz",
        "password": "new_password",
        "business_name": "New Business"
    }, headers=admin_headers)
    assert create_resp.status_code == 200
    assert create_resp.json()["status"] == "success"
    new_user_id = create_resp.json()["user_id"]

    # Verify duplicate username returns 400
    dup_resp = client.post("/admin/create-user", json={
        "username": "new_biz",
        "password": "other_password",
        "business_name": "Duplicate Business"
    }, headers=admin_headers)
    assert dup_resp.status_code == 400

    # Test login of new merchant
    new_login = client.post("/login", json={
        "username": "new_biz",
        "password": "new_password"
    })
    assert new_login.status_code == 200
    assert new_login.json()["business_name"] == "New Business"

    # 2.3 Test Update User as Admin
    update_resp = client.put(f"/admin/update-user/{new_user_id}", json={
        "username": "updated_biz",
        "password": "updated_password",
        "business_name": "Updated Business"
    }, headers=admin_headers)
    assert update_resp.status_code == 200

    # Test login of updated merchant with old credentials (should fail)
    old_login = client.post("/login", json={
        "username": "new_biz",
        "password": "new_password"
    })
    assert old_login.status_code == 401

    # Test login of updated merchant with new credentials (should succeed)
    updated_login = client.post("/login", json={
        "username": "updated_biz",
        "password": "updated_password"
    })
    assert updated_login.status_code == 200
    assert updated_login.json()["business_name"] == "Updated Business"

    # 3. Test 403 Forbidden for non-admin on the new endpoints
    resp = client.post(f"/admin/flush-cache/{user_id}", headers=user_headers)
    assert resp.status_code == 403

    resp = client.delete(f"/admin/wipe-user-data/{user_id}", headers=user_headers)
    assert resp.status_code == 403

    resp = client.delete("/admin/wipe-all-data", headers=user_headers)
    assert resp.status_code == 403

    resp = client.get("/admin/cache-stats", headers=user_headers)
    assert resp.status_code == 403

    resp = client.get(f"/admin/business-details/{user_id}", headers=user_headers)
    assert resp.status_code == 403

    # 4. Test POST /admin/flush-cache/{user_id} as admin
    resp = client.post(f"/admin/flush-cache/{user_id}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # Test invalid user cache flush
    resp = client.post("/admin/flush-cache/9999", headers=admin_headers)
    assert resp.status_code == 404

    # 4.1 Test GET /admin/cache-stats as admin
    resp = client.get("/admin/cache-stats", headers=admin_headers)
    assert resp.status_code == 200
    stats = resp.json()
    assert "context_cache" in stats
    assert "query_cache" in stats

    # 4.2 Test GET /admin/business-details/{user_id} as admin
    resp = client.get(f"/admin/business-details/{user_id}", headers=admin_headers)
    assert resp.status_code == 200
    details = resp.json()
    assert details["username"] == "pharmacy"
    assert "uploads" in details
    assert "invoices" in details
    assert "inventory" in details
    assert "payments" in details
    assert "chat_history" in details

    # Test invalid business details request
    resp = client.get("/admin/business-details/9999", headers=admin_headers)
    assert resp.status_code == 404

    # 4.5 Test DELETE /admin/wipe-user-data/{user_id} as admin
    resp = client.delete(f"/admin/wipe-user-data/{user_id}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # Test invalid user wipe
    resp = client.delete("/admin/wipe-user-data/9999", headers=admin_headers)
    assert resp.status_code == 404

    # 5. Test DELETE /admin/wipe-all-data as admin
    resp = client.delete("/admin/wipe-all-data", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # 6. Verify data tables are empty for the enterprise user
    resp = client.get("/database", headers=user_headers)
    assert resp.status_code == 200
    db_data = resp.json()
    assert len(db_data["invoices"]) == 0
    assert len(db_data["inventory"]) == 0
    assert len(db_data["uploads"]) == 0


def test_pdf_upload_flow():
    # Sign up a new user
    signup_resp = client.post("/signup", json={
        "username": "pdf_merchant",
        "password": "Pdf_password123",
        "business_name": "PDF Business"
    })
    assert signup_resp.status_code == 200
    
    # Login as the new user
    response = client.post("/login", json={
        "username": "pdf_merchant",
        "password": "Pdf_password123"
    })
    assert response.status_code == 200
    token = response.json()["token"]
    user_headers = {"Authorization": f"Bearer {token}"}

    # Prepare mock extracted data
    mock_invoice_data = {
        "invoice_id": "INV-PDF-999",
        "supplier": "Astra Pharma",
        "customer": "MediCare Pharmacy",
        "invoice_date": "2026-06-01",
        "due_date": "2026-07-01",
        "total_amount": 1000.0,
        "status": "Pending",
        "items": [
            {
                "product_name": "Test Medicine X",
                "stock": 50,
                "expiry_date": "2028-06-01",
                "price_per_unit": 20.0
            }
        ]
    }

    # Mock extraction and PDF text helpers to avoid external API calls
    with patch("routes.upload.parse_pdf_text", return_value="Dummy PDF raw invoice text content") as mock_parse, \
         patch("routes.upload.extract_structured_invoice", return_value=mock_invoice_data) as mock_extract, \
         patch("services.pdf_parser.index_new_file_records") as mock_rag_index:

        # Upload dummy PDF file
        pdf_content = b"%PDF-1.4 mock content"
        files = {"file": ("invoice_test.pdf", pdf_content, "application/pdf")}
        
        upload_resp = client.post("/upload", files=files, headers=user_headers)
        
        assert upload_resp.status_code == 200
        resp_data = upload_resp.json()
        assert resp_data["message"] == "Upload successful"
        assert resp_data["file_type"] == "invoice"
        assert resp_data["rows"] == 1

        mock_parse.assert_called_once_with(pdf_content)
        mock_extract.assert_called_once_with("Dummy PDF raw invoice text content")
        assert mock_rag_index.call_count == 3 # Should generate index for invoices, inventory, and payments

    # Verify that the database tables contain the uploaded records
    db_resp = client.get("/database", headers=user_headers)
    assert db_resp.status_code == 200
    db_data = db_resp.json()
    
    assert len(db_data["invoices"]) == 1
    assert db_data["invoices"][0]["invoice_id"] == "INV-PDF-999"
    assert db_data["invoices"][0]["amount"] == 1000.0
    
    assert len(db_data["inventory"]) == 1
    assert db_data["inventory"][0]["product"] == "Test Medicine X"
    assert db_data["inventory"][0]["stock"] == 50
    
    assert len(db_data["uploads"]) == 1
    assert db_data["uploads"][0]["filename"] == "invoice_test.pdf"


def test_password_policy_signup():
    # Short password
    response = client.post("/signup", json={
        "username": "user_short",
        "password": "pwd",
        "business_name": "Short Business"
    })
    assert response.status_code == 400
    assert "at least 8 characters" in response.json()["detail"]

    # No uppercase
    response = client.post("/signup", json={
        "username": "user_no_upper",
        "password": "password123",
        "business_name": "No Upper Business"
    })
    assert response.status_code == 400
    assert "uppercase" in response.json()["detail"]

    # No lowercase
    response = client.post("/signup", json={
        "username": "user_no_lower",
        "password": "PASSWORD123",
        "business_name": "No Lower Business"
    })
    assert response.status_code == 400
    assert "lowercase" in response.json()["detail"]

    # No number
    response = client.post("/signup", json={
        "username": "user_no_number",
        "password": "Password",
        "business_name": "No Number Business"
    })
    assert response.status_code == 400
    assert "number" in response.json()["detail"]


def test_login_rate_limiting():
    # Call /login 11 times. The 11th call should trigger rate limiting.
    from services.rate_limiter import _ip_window
    _ip_window.clear()

    for i in range(10):
        response = client.post("/login", json={
            "username": "pharmacy",
            "password": "wrongpassword"
        })
        # Rate limit is 10, so these should be 401 (Invalid credentials)
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials"

    # 11th request should be rate limited (429)
    response = client.post("/login", json={
        "username": "pharmacy",
        "password": "wrongpassword"
    })
    assert response.status_code == 429
    assert "Rate limit exceeded" in response.json()["detail"]


def test_upload_limits():
    # Sign up a new user to ensure clean isolated state
    signup_resp = client.post("/signup", json={
        "username": "upload_merchant",
        "password": "Upload_password123",
        "business_name": "Upload Business"
    })
    assert signup_resp.status_code == 200
    token = signup_resp.json()["token"]
    user_headers = {"Authorization": f"Bearer {token}"}

    # 1. Large file upload (exceeding 5MB limit)
    large_content = b"a" * (5 * 1024 * 1024 + 1)
    files = {"file": ("large_file.csv", large_content, "text/csv")}
    response = client.post("/upload", files=files, headers=user_headers)
    assert response.status_code == 413
    assert "File size exceeds maximum limit" in response.json()["detail"]

    # 2. CSV file with too many rows (> 1000 rows)
    # Header row + 1001 rows of data
    rows = ["invoice_id,customer,product,amount,status,due_date"]
    for i in range(1001):
        rows.append(f"INV-{i},Customer-{i},Product-{i},100.0,Pending,2026-06-01")
    csv_content = "\n".join(rows).encode("utf-8")
    files = {"file": ("too_many_rows.csv", csv_content, "text/csv")}
    response = client.post("/upload", files=files, headers=user_headers)
    assert response.status_code == 400
    assert "Row count exceeds maximum limit" in response.json()["detail"]


def test_upload_rate_limiting():
    # Sign up a new user to ensure clean isolated state
    signup_resp = client.post("/signup", json={
        "username": "upload_rate_merchant",
        "password": "Upload_password123",
        "business_name": "Upload Rate Business"
    })
    assert signup_resp.status_code == 200
    token = signup_resp.json()["token"]
    user_headers = {"Authorization": f"Bearer {token}"}

    # Clear rate limit state
    from services.rate_limiter import _upload_window
    _upload_window.clear()

    # Small valid CSV content
    csv_content = "invoice_id,customer,product,amount,status,due_date\nINV-001,Cust,Prod,50.0,Pending,2026-06-01".encode("utf-8")

    # Call /upload 5 times. Vary content slightly to avoid 409.
    for i in range(5):
        csv_var = f"invoice_id,customer,product,amount,status,due_date\nINV-{i},Cust,Prod,50.0,Pending,2026-06-01".encode("utf-8")
        files = {"file": (f"test_{i}.csv", csv_var, "text/csv")}
        response = client.post("/upload", files=files, headers=user_headers)
        assert response.status_code in [200, 409]

    # 6th call should trigger 429
    files = {"file": ("test_6.csv", csv_content, "text/csv")}
    response = client.post("/upload", files=files, headers=user_headers)
    assert response.status_code == 429
    assert "Rate limit exceeded" in response.json()["detail"]


def test_sanitized_errors():
    # Verify that admin/rate-limits/{user_id} hides the database exception
    admin_login = client.post("/login", json={
        "username": "admin",
        "password": "admin123"
    })
    admin_token = admin_login.json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Set rate limits endpoint mock-triggering an error
    with patch("routes.admin.SessionLocal") as mock_session:
        mock_db = MagicMock()
        mock_db.query.side_effect = Exception("Internal DB Connection Corrupted Stack Trace Info")
        mock_session.return_value = mock_db

        # Try to call set_rate_limits
        response = client.post("/admin/rate-limits/1", json={
            "requests_per_minute": 10,
            "requests_per_day": 500,
            "max_tokens_per_day": 50000,
            "complex_per_day": 20,
            "active": True
        }, headers=admin_headers)

        assert response.status_code == 500
        # Should NOT leak the database exception detail
        assert "Internal DB Connection Corrupted" not in response.json()["detail"]
        assert response.json()["detail"] == "Internal server error setting rate limits."
