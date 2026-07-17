"""
Debug why invoice_line_items are skipped during remap import.
Simulates exactly what _import_with_remap does for a fake line item row.
"""
import sys
sys.path.insert(0, 'backend')
import logging
logging.basicConfig(level=logging.DEBUG)

from database.db import engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

# Simulate params from the sync log
source_owner_id = 42   # cloud business id
dest_owner_id   = 133  # local business id

with Session(engine) as db:
    insp = inspect(db.bind)
    col_info = insp.get_columns('invoice_line_items')
    fks      = insp.get_foreign_keys('invoice_line_items')
    pk_info  = insp.get_pk_constraint('invoice_line_items')

    col_names = {c['name'] for c in col_info}
    fk_targets = [
        (fk['constrained_columns'][0], fk['referred_table'])
        for fk in fks
        if len(fk.get('constrained_columns', [])) == 1
        and fk.get('referred_columns') == ['id']
    ]
    pk_cols = set(pk_info.get('constrained_columns', []))

    print("col_names:", sorted(col_names))
    print("fk_targets:", fk_targets)
    print("pk_cols:", pk_cols)

    # Simulate: invoices id_map built from cloud (cloud_pk=19 → local_pk=816 for LCL-OW-0019)
    inv = db.execute(text("SELECT id, invoice_id, uid FROM invoices WHERE invoice_id='LCL-OW-0019'")).fetchone()
    print(f"\nLCL-OW-0019 → local id={inv[0] if inv else 'NOT FOUND'}")

    if inv:
        local_pk = inv[0]
        # Suppose cloud exported it with cloud_pk=19 (we don't know exact but let's test with any)
        fake_cloud_pk = 19
        id_maps = {'invoices': {fake_cloud_pk: local_pk}}

        # Fake line item row as exported from cloud
        fake_row = {
            'id': 99,
            'invoice_id': fake_cloud_pk,
            'product_id': None,
            'product_name': 'Sugar 1kg',
            'description': None,
            'hsn_sac': '1701',
            'unit': 'Kg',
            'quantity': 2,
            'unit_price': 50.0,
            'discount': 0,
            'discount_pct': 0,
            'taxable_value': 100.0,
            'cgst_rate': 2.5,
            'cgst_amount': 2.5,
            'sgst_rate': 2.5,
            'sgst_amount': 2.5,
            'igst_rate': 0,
            'igst_amount': 0,
            'cess_rate': 0,
            'cess_amount': 0,
            'line_total': 105.0,
            'created_at': '2026-07-12T21:48:00',
            'updated_at': '2026-07-12T21:48:00',
            'uid': 'test-uid-12345',
            'mrp': None,
            'expiry_date': None,
            'attributes': None,
            'batch_no': None,
            'serial_no': None,
            'business_id': source_owner_id,  # does line_item have business_id?
        }

        # Step 1: filter to existing columns only, drop id
        filtered = {k: v for k, v in fake_row.items() if k in col_names and k != 'id'}
        print("\nFiltered row (after column filter, no id):", list(filtered.keys()))

        # Step 2: owner remap
        for f in ('business_id', 'parent_business_id', 'user_id'):
            if f in filtered and filtered[f] == source_owner_id:
                filtered[f] = dest_owner_id
                print(f"  Remapped {f}: {source_owner_id} → {dest_owner_id}")

        # Step 3: FK rewriting
        print("\nFK rewriting:")
        for col, ref_table in fk_targets:
            if filtered.get(col) is not None:
                m = id_maps.get(ref_table)
                print(f"  {col} → {ref_table}: map={m}, value={filtered.get(col)}")
                if m and filtered[col] in m:
                    old = filtered[col]
                    filtered[col] = m[filtered[col]]
                    print(f"    Remapped {col}: {old} → {filtered[col]}")
                else:
                    print(f"    NOT remapped (cloud_pk not in map)")

        # Step 4: uid lookup
        uid = filtered.get('uid')
        print(f"\nUID lookup for '{uid}':")
        if uid:
            row = db.execute(text("SELECT id FROM invoice_line_items WHERE uid = :u LIMIT 1"), {'u': uid}).fetchone()
            print(f"  Existing: {row}")

        # Step 5: try insert
        print(f"\nFinal invoice_id to be inserted: {filtered.get('invoice_id')}")
        cols_to_insert = list(filtered.keys())
        col_str = ', '.join(f'"{c}"' for c in cols_to_insert)
        ph = ', '.join(f':{c}' for c in cols_to_insert)
        sql = f'INSERT INTO "invoice_line_items" ({col_str}) VALUES ({ph})'
        print("SQL:", sql[:120])
        try:
            with db.begin_nested():
                new_id = db.execute(text(sql), filtered).lastrowid
            print(f"  INSERT succeeded, new_id={new_id}")
            db.rollback()
        except Exception as e:
            print(f"  INSERT FAILED: {e}")
