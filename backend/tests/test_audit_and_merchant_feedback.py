import os
import sys
import pytest
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from main_groq import app
from database.db import SessionLocal, Base, current_user_id_var, current_username_var
from database.models import User, UserFeedback, TableAlteration

client = TestClient(app)
BID = 999111

def _ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()

def _clear():
    db = SessionLocal()
    try:
        db.query(User).filter(User.public_id == "test-biz-uid").delete()
        db.query(UserFeedback).filter(UserFeedback.business_id == BID).delete()
        db.query(TableAlteration).filter(TableAlteration.business_id == BID).delete()
        db.commit()
    except Exception:
        pass
    finally:
        db.close()

@pytest.fixture(autouse=True)
def _setup():
    _ensure_schema()
    _clear()
    yield
    _clear()


def test_table_alteration_audit_hooks():
    """Verify that inserting and updating a model (excluding audit tables) logs events to TableAlteration."""
    db = SessionLocal()
    try:
        # 1. Set user context variables
        current_user_id_var.set(123)
        current_username_var.set("test-audit-operator")

        # 2. Perform an INSERT
        test_user = User(
            username="audit_test_user",
            password="mockpassword",
            business_name="Audit Test Corp",
            public_id="test-biz-uid"
        )
        db.add(test_user)
        db.commit()
        db.refresh(test_user)

        # 3. Verify TableAlteration record was written
        insert_audit = (db.query(TableAlteration)
                        .filter(TableAlteration.table_name == "users", TableAlteration.action == "INSERT")
                        .order_by(TableAlteration.id.desc())
                        .first())
        assert insert_audit is not None
        assert insert_audit.user_id == 123
        assert insert_audit.username == "test-audit-operator"
        assert "audit_test_user" in insert_audit.new_values

        # 4. Perform an UPDATE
        test_user.business_name = "Audited Updated Name"
        db.commit()

        # 5. Verify UPDATE record was written
        update_audit = (db.query(TableAlteration)
                        .filter(TableAlteration.table_name == "users", TableAlteration.action == "UPDATE")
                        .order_by(TableAlteration.id.desc())
                        .first())
        assert update_audit is not None
        assert "Audited Updated Name" in update_audit.new_values
        assert "Audit Test Corp" in update_audit.old_values

    finally:
        db.close()
        # Clean context
        current_user_id_var.set(None)
        current_username_var.set(None)


def test_merchant_feedback_model_insertion():
    """Verify that UserFeedback records can be stored and queried cleanly."""
    db = SessionLocal()
    try:
        feedback = UserFeedback(
            business_id=BID,
            username="varshini_feedback",
            message="Logs are missing on space startup.",
            log_file_path="logs/remote_clients/feedback_log.tar.gz"
        )
        db.add(feedback)
        db.commit()
        db.refresh(feedback)

        retrieved = db.query(UserFeedback).filter(UserFeedback.business_id == BID).first()
        assert retrieved is not None
        assert retrieved.username == "varshini_feedback"
        assert "Logs are missing" in retrieved.message
        assert retrieved.log_file_path == "logs/remote_clients/feedback_log.tar.gz"
    finally:
        db.close()
