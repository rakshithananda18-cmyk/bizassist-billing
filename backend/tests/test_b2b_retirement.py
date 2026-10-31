"""Account retirement preserves the counterparty's independent financial books."""
import pytest

from database.db import SessionLocal
from database.models import User, Invoice, PurchaseInvoice
from core.models import B2BOrder, B2BConnection, B2BLedger, JournalEntry, StockLedger
from core.party_archive import DocumentPartySnapshot, document_party_metadata, require_active_businesses
from core.billing.print_payload import build_print_payload
from core.order.service import b2b_purchase_invoice_uid
from services.admin_service import wipe_user_data
from tests.test_phase4_sync import _signup, _connect, _place_and_complete, client


@pytest.fixture(autouse=True)
def rate_limit_reset():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()


@pytest.mark.parametrize("deleted_side", ["seller", "buyer"])
def test_completed_trade_survives_account_retirement(deleted_side):
    seller, buyer = _signup("Retirement Seller"), _signup("Retirement Buyer")
    with SessionLocal() as db:
        for info, address in ((seller, "Seller historical address"), (buyer, "Buyer historical address")):
            db.get(User, info["bid"]).address = address
        db.commit()
    _connect(seller, buyer)
    _, order_id, _ = _place_and_complete(seller, buyer, 2)
    retiring = seller if deleted_side == "seller" else buyer
    surviving = buyer if deleted_side == "seller" else seller
    with SessionLocal() as db:
        order = db.get(B2BOrder, order_id)
        invoice = db.get(Invoice, order.seller_invoice_id)
        purchase = db.query(PurchaseInvoice).filter_by(business_id=buyer["bid"], uid=b2b_purchase_invoice_uid(order)).one()
        original_bizid = db.get(User, retiring["bid"]).public_id
        sale_id, bill_id, sale_number = invoice.id, purchase.id, invoice.invoice_id
        document = purchase if deleted_side == "seller" else invoice
        kind = "purchase" if deleted_side == "seller" else "sale"
        total = document.total_amount
        journal_before = [(r.id, r.source_type, r.source_id) for r in db.query(JournalEntry).filter_by(business_id=surviving["bid"]).order_by(JournalEntry.id)]
        stock_before = [(r.id, r.product_id, r.qty_delta) for r in db.query(StockLedger).filter_by(business_id=surviving["bid"]).order_by(StockLedger.id)]
        ledger_ids = [r.id for r in db.query(B2BLedger).filter_by(seller_business_id=seller["bid"], buyer_business_id=buyer["bid"])]
        # Profile edits after issue cannot change the original printed party.
        db.get(User, retiring["bid"]).business_name = "Edited later"
        db.get(User, retiring["bid"]).address = "Edited later address"
        db.commit()
        result = wipe_user_data(retiring["bid"], db)
        assert result["status"] == "success"
        db.expire_all()
        archived = db.get(User, retiring["bid"])
        assert archived.role == "deleted" and archived.public_id == original_bizid
        assert archived.address is None and archived.password.startswith("!retired:")
        kept = db.get(PurchaseInvoice, bill_id) if deleted_side == "seller" else db.get(Invoice, sale_id)
        assert kept is not None and kept.total_amount == total
        metadata = document_party_metadata(kept, kind)
        assert metadata["counterparty_deleted"] is True
        assert metadata["parties"][deleted_side]["address"] == deleted_side.title() + " historical address"
        assert metadata["parties"][deleted_side]["name"] == "Retirement " + deleted_side.title()
        assert [(r.id, r.source_type, r.source_id) for r in db.query(JournalEntry).filter_by(business_id=surviving["bid"]).order_by(JournalEntry.id)] == journal_before
        assert [(r.id, r.product_id, r.qty_delta) for r in db.query(StockLedger).filter_by(business_id=surviving["bid"]).order_by(StockLedger.id)] == stock_before
        assert [r.id for r in db.query(B2BLedger).filter_by(seller_business_id=seller["bid"], buyer_business_id=buyer["bid"])] == ledger_ids
        archived_order = db.get(B2BOrder, order_id)
        assert archived_order.status == "completed" and getattr(archived_order, deleted_side + "_deleted")
        if deleted_side == "seller":
            assert archived_order.seller_invoice_id is None and archived_order.seller_invoice_uid
            assert all(line.product_id is None and line.product_name for line in archived_order.line_items)
        else:
            payload = build_print_payload(db, business_id=seller["bid"], invoice_no=sale_number)
            assert payload["buyer"]["name"] == "Retirement Buyer"
            assert payload["buyer"]["billing_address"] == "Buyer historical address"
            assert payload["buyer"]["deleted"] is True
            # The surviving owner can still post a legitimate private return;
            # the new note must retain the retired counterparty's identity.
            from core.billing.commands import create_credit_note
            note = create_credit_note(db, business_id=seller["bid"], original_invoice_id=sale_id,
                lines=[{"product_id": kept.line_items[0].product_id, "qty": 1, "reason": "Synthetic return"}])
            note_parties = document_party_metadata(note, "sale")
            assert note_parties["buyer_deleted"] is True
            assert note_parties["parties"]["buyer"]["name"] == "Retirement Buyer"
        assert db.query(B2BConnection).filter_by(seller_business_id=seller["bid"], buyer_business_id=buyer["bid"]).one().status == "revoked"
        with pytest.raises(ValueError, match="deleted"):
            require_active_businesses(db, retiring["bid"], surviving["bid"])
    assert client.get("/orders", headers=retiring["headers"]).status_code == 401
    history = client.get(f"/orders/{order_id}", headers=surviving["headers"])
    assert history.status_code == 200, history.text
    assert history.json()["counterparty_deleted"] is True


def test_party_capture_cannot_replace_an_issued_identity():
    from core.party_archive import capture_document_parties
    owner = _signup("Immutable seller")
    with SessionLocal() as db:
        user = db.get(User, owner["bid"])
        invoice = Invoice(business_id=user.id, invoice_id="SNAPSHOT-ONLY", amount=0, total_amount=0)
        db.add(invoice)
        first = capture_document_parties(db, invoice, kind="sale", seller=user, buyer={"name": "Original customer", "gstin": "SYNTHETIC"})
        db.flush()
        again = capture_document_parties(db, invoice, kind="sale", seller=user, buyer={"name": "Different customer"})
        assert first is again
        assert "Original customer" in again.buyer_json
        assert db.query(DocumentPartySnapshot).filter_by(business_id=user.id).count() == 1
        db.rollback()
