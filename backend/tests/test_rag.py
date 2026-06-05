import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

# Set test environment variables
os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist_rag.db"
os.environ["OPENAI_API_KEY"] = "mock_openai_api_key"

# Clean up any leftover databases
for db_path in ["test_bizassist_rag.db", "backend/test_bizassist_rag.db"]:
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

# Ensure backend folder is in path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from database.db import engine, SessionLocal
from database.models import Base, Invoice, Inventory, Payment, DocumentEmbedding, User
from services.embeddings import (
    make_invoice_text,
    make_inventory_text,
    make_payment_text,
    index_new_file_records,
    semantic_search_records
)
from services.tools import query_semantic_index

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    # Clear existing data to avoid conflicts with previous tests sharing the DB instance
    db.query(Invoice).delete()
    db.query(Inventory).delete()
    db.query(Payment).delete()
    db.query(DocumentEmbedding).delete()
    db.query(User).delete()
    db.commit()

    # Create test user/business
    user = User(id=10, username="rag_user", password="hashed_password", business_name="RAG Store", role="enterprise")
    db.add(user)
    db.commit()
    db.close()
    
    yield
    
    Base.metadata.drop_all(bind=engine)
    try:
        os.remove("test_bizassist_rag.db")
    except Exception:
        pass

def test_serializers():
    inv = Invoice(invoice_id="INV-001", customer="Cipla", amount=1500.50, status="Pending", invoice_date="2026-06-01", due_date="2026-06-15")
    inv_text = make_invoice_text(inv)
    assert "INV-001" in inv_text
    assert "Cipla" in inv_text
    assert "₹1,500.50" in inv_text
    assert "Pending" in inv_text
    assert "2026-06-15" in inv_text

    item = Inventory(product_name="Paracetamol", stock=8, expiry_date="2027-01-01", supplier="AstraZeneca")
    item_text = make_inventory_text(item)
    assert "Paracetamol" in item_text
    assert "8 units" in item_text
    assert "Low stock!" in item_text
    assert "AstraZeneca" in item_text

    pmt = Payment(customer="Apollo Pharmacy", amount=25000.00, due_date="2026-05-30", paid="Yes")
    pmt_text = make_payment_text(pmt)
    assert " Apollo Pharmacy" in pmt_text
    assert "₹25,000.00" in pmt_text
    assert "Paid" in pmt_text

@patch("services.embeddings.generate_embeddings_batch")
def test_indexing_and_search(mock_batch_embeddings):
    # Mock return values for embeddings
    # We use 3 floats for a simplified 3D embedding space for our tests
    mock_batch_embeddings.side_effect = [
        [[1.0, 0.0, 0.0]],  # First call (Invoice)
        [[0.0, 1.0, 0.0]]   # Second call (Inventory)
    ]
    
    db = SessionLocal()
    
    # 1. Add mock records to db
    inv = Invoice(business_id=10, file_id=5, invoice_id="INV-RAG", customer="RAG Pharmacy", amount=100.0, status="Paid")
    item = Inventory(business_id=10, file_id=5, product_name="RAG Medicine", stock=50, supplier="RAG Supplier")
    db.add(inv)
    db.add(item)
    db.commit()
    
    # 2. Run index sync
    index_new_file_records(db, "invoice", file_id=5, business_id=10)
    index_new_file_records(db, "inventory", file_id=5, business_id=10)
    
    # Verify embeddings were saved in the db
    embeddings_count = db.query(DocumentEmbedding).filter(DocumentEmbedding.business_id == 10).count()
    assert embeddings_count == 2
    
    # Verify records have the correct fields
    inv_emb = db.query(DocumentEmbedding).filter(DocumentEmbedding.document_type == "invoice").first()
    assert inv_emb is not None
    assert inv_emb.record_id == inv.id
    assert inv_emb.file_id == 5
    assert json.loads(inv_emb.embedding_json) == [1.0, 0.0, 0.0]
    
    db.close()

    # 3. Test semantic search cosine similarity calculations
    # We patch the single generate_embedding call for the query vector
    with patch("services.embeddings.generate_embedding") as mock_single_embedding:
        # Scenario A: Query vector close to X-axis -> matches Invoice
        mock_single_embedding.return_value = [0.9, 0.1, 0.0]
        results = semantic_search_records(user_id=10, query="Need billing info", limit=5)
        
        assert len(results) == 2
        assert results[0]["document_type"] == "invoice"  # closest match
        assert results[0]["score"] > 0.8
        
        # Scenario B: Query vector close to Y-axis -> matches Inventory
        mock_single_embedding.return_value = [0.1, 0.9, 0.0]
        results = semantic_search_records(user_id=10, query="Show stock", limit=5)
        
        assert len(results) == 2
        assert results[0]["document_type"] == "inventory"
        assert results[0]["score"] > 0.8

def test_tool_execution():
    with patch("services.tools.semantic_search_records") as mock_search_records:
        mock_search_records.return_value = [
            {"score": 0.95, "document_type": "invoice", "record_id": 1, "text_content": "Matched Invoice Text"}
        ]
        
        response_json = query_semantic_index(user_id=10, query="unpaid clients", limit=2)
        results = json.loads(response_json)
        
        assert len(results) == 1
        assert results[0]["text_content"] == "Matched Invoice Text"
        mock_search_records.assert_called_once_with(10, "unpaid clients", 2)
