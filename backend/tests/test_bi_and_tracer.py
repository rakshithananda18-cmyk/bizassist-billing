import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from database.models import Base, Invoice, User, Product
from services.api_tracer import record_request, get_recent_traces, get_trace_by_id, get_console_metrics
from services.bi_analytics import get_bi_dashboard_metrics

@pytest.fixture
def mock_db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(id=1, username='merchant_one', password='hash', business_name='Merchant Alpha')
        db.add(user)
        inv = Invoice(id=1, business_id=1, invoice_id='INV-101', total_amount=1500.0, paid_amount=1500.0, payment_mode='upi', created_at=datetime.now(timezone.utc))
        db.add(inv)
        db.commit()
        yield db
    engine.dispose()

def test_api_tracer_lifecycle():
    tid = record_request(
        method="GET",
        path="/api/invoices",
        status_code=200,
        duration_ms=45.2,
        ip="192.168.1.10",
        biz_id="biz_test_001"
    )
    assert tid.startswith("trc_")
    
    traces = get_recent_traces(limit=10)
    assert any(t["id"] == tid for t in traces)
    
    trace = get_trace_by_id(tid)
    assert trace is not None
    assert trace["status"] == 200
    assert trace["method"] == "GET"
    assert trace["duration_ms"] == 45.2

    metrics = get_console_metrics()
    assert "traffic" in metrics
    assert "latency" in metrics
    assert "cost" in metrics
    assert metrics["cost"]["current_monthly_usd"] == 0.0

def test_bi_analytics_with_data(mock_db):
    data = get_bi_dashboard_metrics(mock_db, days=30)
    assert "kpis" in data
    assert "daily_trends" in data
    assert "payment_breakdown" in data
    assert "top_merchants" in data
    assert data["kpis"]["total_revenue_all"] == 1500.0
    assert data["kpis"]["total_invoices_all"] == 1
    assert len(data["daily_trends"]) in (30, 31)
    assert len(data["top_merchants"]) == 1
    assert data["top_merchants"][0]["business_name"] == "Merchant Alpha"
