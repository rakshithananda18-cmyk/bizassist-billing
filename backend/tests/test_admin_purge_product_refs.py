"""Business deletion must preserve a surviving business's financial snapshots."""
import uuid

import pytest
from fastapi import HTTPException

from database.db import SessionLocal
from database.models import User, Product, Invoice, InvoiceLineItem, DeletedBusiness
from core.models import B2BOrder, B2BOrderLineItem
from services.admin_service import wipe_user_data


def business(db):
    token = uuid.uuid4().hex[:12]
    user = User(username='purge_fixture_' + token, password='unusable',
                public_id='BA-' + token.upper(), business_name='Purge fixture', role='owner')
    db.add(user)
    db.flush()
    return user


def test_purge_detaches_optional_foreign_product_reference_and_preserves_invoice():
    with SessionLocal() as db:
        owner, survivor = business(db), business(db)
        owner_id, survivor_id, retired_bizid = owner.id, survivor.id, owner.public_id
        product = Product(business_id=owner.id, name='Historical fixture')
        invoice = Invoice(business_id=survivor.id, invoice_id='FIX-' + uuid.uuid4().hex,
                          total_amount=12, amount=12)
        db.add_all([product, invoice])
        db.flush()
        line = InvoiceLineItem(invoice_id=invoice.id, product_id=product.id,
                               product_name='Historical fixture', quantity=2, unit_price=6, line_total=12)
        db.add(line)
        db.commit()
        line_id, invoice_id = line.id, invoice.id
        wipe_user_data(owner_id, db)
        db.expire_all()
        assert db.get(User, owner_id) is None
        assert db.get(User, survivor_id) is not None
        assert db.get(Invoice, invoice_id).total_amount == 12
        kept = db.get(InvoiceLineItem, line_id)
        assert kept.product_id is None
        assert (kept.product_name, kept.quantity, kept.line_total) == ('Historical fixture', 2, 12)
        assert db.query(DeletedBusiness).filter_by(public_id=retired_bizid, reason='admin_wipe').count() == 1


def test_required_foreign_product_reference_stops_before_any_purge():
    with SessionLocal() as db:
        owner, seller, buyer = business(db), business(db), business(db)
        product = Product(business_id=owner.id, name='Required fixture')
        owned_invoice = Invoice(business_id=owner.id, invoice_id='OWN-' + uuid.uuid4().hex, total_amount=5)
        order = B2BOrder(seller_business_id=seller.id, buyer_business_id=buyer.id,
                         order_number='FOREIGN-' + uuid.uuid4().hex, order_date='2026-10-01', total_amount=5)
        db.add_all([product, owned_invoice, order])
        db.flush()
        line = B2BOrderLineItem(order_id=order.id, product_id=product.id,
                               product_name='Required fixture', quantity=1, unit_price=5, line_total=5)
        db.add(line)
        db.commit()
        ids = owner.id, product.id, owned_invoice.id, line.id
        with pytest.raises(HTTPException) as error:
            wipe_user_data(owner.id, db)
        assert error.value.status_code == 409
        # Even before rollback, nothing belonging to either business was removed.
        assert db.get(User, ids[0]) is not None
        assert db.get(Product, ids[1]) is not None
        assert db.get(Invoice, ids[2]) is not None
        assert db.get(B2BOrderLineItem, ids[3]).product_id == ids[1]
        db.rollback()
