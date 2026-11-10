"""History fields never become mutable merely because they crossed sync."""
SETTLEMENTS = frozenset({"supplier_payments", "customer_refunds", "customer_credit_allocations"})


def protect_history(entity, data, existing):
    if existing is None:
        return
    if entity in SETTLEMENTS or entity == "document_party_snapshots":
        ignored = {"id", "created_at", "updated_at", "seller_deleted", "buyer_deleted"}
        for column in existing.__table__.columns:
            key = column.name
            if key not in ignored and key in data and data[key] != getattr(existing, key):
                raise ValueError(f"Immutable {entity}.{key} differs from its posted value")
    if entity in {"document_party_snapshots", "b2b_connections", "b2b_orders"}:
        for key in ("seller_snapshot", "buyer_snapshot"):
            prior = getattr(existing, key, None)
            if prior is not None and key in data and data[key] != prior:
                raise ValueError(f"Posted party snapshot {key} cannot be rewritten")
        for key in ("seller_deleted", "buyer_deleted"):
            if key in data:
                data[key] = bool(data[key] or getattr(existing, key, False))
