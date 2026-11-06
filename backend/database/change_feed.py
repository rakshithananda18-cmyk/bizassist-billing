"""Commit-ordered replication, captured by database triggers (including raw SQL).

Every writer increments a per-business clock under a row lock held to commit.
Consequently revision N+1 cannot become visible before N commits or rolls back.
SQLite's single writer gives the same guarantee. No wall clock is a cursor.
"""
from __future__ import annotations
import json
from sqlalchemy import text, inspect


def _sources(connection):
    from database.sync_map import MODEL_MAP
    present = set(inspect(connection).get_table_names())
    return {name: model for name, model in MODEL_MAP.items() if name in present}


def install_change_feed(connection, **_kw):
    """Install/refresh triggers and backfill existing rows exactly once per UID.

    Called inside the schema owner's transaction, never by an HTTP app role.
    Trigger writes are fail-closed: a business mutation cannot commit without
    its event. Existing records are seeded while the same writer locks apply.
    """
    from database.models import SyncFeedClock, SyncFeedEvent
    SyncFeedClock.__table__.create(connection, checkfirst=True)
    SyncFeedEvent.__table__.create(connection, checkfirst=True)
    pg = connection.dialect.name == "postgresql"
    if pg:
        connection.execute(text("SELECT pg_advisory_xact_lock(724839102)"))
        connection.execute(text("""
            CREATE OR REPLACE FUNCTION bizassist_feed_emit(bid integer, ent text, body jsonb, op text)
            RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
            DECLARE rev bigint;
            BEGIN
              IF bid IS NULL THEN RETURN; END IF;
              INSERT INTO sync_feed_clock(business_id,revision) VALUES(bid,1)
              ON CONFLICT(business_id) DO UPDATE SET revision=sync_feed_clock.revision+1
              RETURNING revision INTO rev;
              INSERT INTO sync_feed_events(business_id,revision,entity,row_uid,operation,payload)
              VALUES(bid,rev,ent,COALESCE(body->>'uid',body->>'id'),op,body::text);
            END $$;
            REVOKE ALL ON FUNCTION bizassist_feed_emit(integer,text,jsonb,text) FROM PUBLIC;
        """))
    for name, model in sorted(_sources(connection).items(), key=lambda x: x[0]):
        cols = {c["name"] for c in inspect(connection).get_columns(name)}
        owner_sql = _owner_expressions(name, cols)
        if not owner_sql:
            raise RuntimeError(f"No change-feed ownership rule for {name}")
        if pg:
            calls = " ".join(f"PERFORM bizassist_feed_emit(({expr}),TG_TABLE_NAME,body,TG_OP);" for expr in owner_sql)
            try:
                connection.execute(text(f"""
                CREATE OR REPLACE FUNCTION bizassist_feed_{name}() RETURNS trigger
                LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
                DECLARE body jsonb;
                BEGIN
                  body := CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
                  {calls}
                  RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
                END $$;
                DROP TRIGGER IF EXISTS bizassist_feed_capture ON "{name}";
                CREATE TRIGGER bizassist_feed_capture BEFORE INSERT OR UPDATE OR DELETE ON "{name}"
                FOR EACH ROW EXECUTE FUNCTION bizassist_feed_{name}();
            """))
            except Exception as e:
                if "deadlock" in str(e).lower() or "lock" in str(e).lower():
                    logger.warning(f"[change_feed] Concurrent migration on table {name} (peer installed trigger): {e}")
                else:
                    raise
            # BEFORE INSERT does not see an ORM-generated id when the PK is
            # server-generated? PostgreSQL defaults are assigned before this
            # trigger, while UID defaults are assigned by SQLAlchemy before SQL.
        else:
            for op in ("INSERT", "UPDATE", "DELETE"):
                ref = "OLD" if op == "DELETE" else "NEW"
                body = "json_object(" + ",".join(f"'{c}',{ref}.\"{c}\"" for c in sorted(cols)) + ")"
                statements = []
                for expr in owner_sql:
                    bid = _sqlite_owner(expr, ref)
                    statements += [
                        f"INSERT INTO sync_feed_clock(business_id,revision) SELECT {bid},0 WHERE {bid} IS NOT NULL ON CONFLICT(business_id) DO NOTHING;",
                        f"UPDATE sync_feed_clock SET revision=revision+1 WHERE business_id={bid};",
                        f"INSERT INTO sync_feed_events(business_id,revision,entity,row_uid,operation,payload) SELECT {bid},revision,'{name}',CAST(COALESCE(json_extract({body},'$.uid'),json_extract({body},'$.id')) AS TEXT),'{op}',{body} FROM sync_feed_clock WHERE business_id={bid};",
                    ]
                trigger = f"bizassist_feed_{name}_{op.lower()}"
                timing = "BEFORE" if op == "DELETE" else "AFTER"
                connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS "{trigger}"')
                connection.exec_driver_sql(f'CREATE TRIGGER "{trigger}" {timing} {op} ON "{name}" BEGIN ' + " ".join(statements) + " END")
        # Seed records absent from the event history; the owner migration holds
        # the global DDL lock and the clock row locks until this transaction ends.
        rows = connection.execute(text(f'SELECT * FROM "{name}"')).mappings().all()
        for row in rows:
            body = dict(row)
            uid = str(body.get("uid") or body.get("id"))
            for bid in _owners_for_seed(connection, name, body):
                exists = connection.execute(text("SELECT 1 FROM sync_feed_events WHERE business_id=:b AND entity=:e AND row_uid=:u LIMIT 1"), {"b": bid, "e": name, "u": uid}).first()
                if exists:
                    continue
                encoded = json.dumps(body, default=lambda x: x.isoformat() if hasattr(x, "isoformat") else str(x))
                if pg:
                    connection.execute(text("SELECT bizassist_feed_emit(:b,:e,CAST(:p AS jsonb),'INSERT')"), {"b": bid, "e": name, "p": encoded})
                else:
                    connection.execute(text("INSERT INTO sync_feed_clock(business_id,revision) VALUES(:b,0) ON CONFLICT(business_id) DO NOTHING"), {"b": bid})
                    connection.execute(text("UPDATE sync_feed_clock SET revision=revision+1 WHERE business_id=:b"), {"b": bid})
                    connection.execute(text("INSERT INTO sync_feed_events(business_id,revision,entity,row_uid,operation,payload) SELECT :b,revision,:e,:u,'INSERT',:p FROM sync_feed_clock WHERE business_id=:b"), {"b": bid, "e": name, "u": uid, "p": encoded})


_CHILD = {"invoice_line_items": ("invoices", "invoice_id"), "purchase_invoice_line_items": ("purchase_invoices", "purchase_invoice_id"), "purchase_order_line_items": ("purchase_orders", "purchase_order_id"), "stock_transfer_line_items": ("stock_transfers", "transfer_id"), "b2b_order_line_items": ("b2b_orders", "order_id"), "shift_cash_movements": ("register_shifts", "shift_id")}


def _owner_expressions(name, cols):
    if "business_id" in cols:
        return ["(body->>'business_id')::integer"]
    if {"seller_business_id", "buyer_business_id"} <= cols:
        # Deterministic lock order for shared records.
        return ["LEAST((body->>'seller_business_id')::integer,(body->>'buyer_business_id')::integer)", "GREATEST((body->>'seller_business_id')::integer,(body->>'buyer_business_id')::integer)"]
    if name in _CHILD:
        parent, fk = _CHILD[name]
        owners = ("seller_business_id", "buyer_business_id") if parent == "b2b_orders" else ("business_id",)
        return [f"SELECT {owner} FROM {parent} WHERE id=(body->>'{fk}')::integer" for owner in owners]
    return []


def _sqlite_owner(expr, ref):
    import re
    out = re.sub(r"\(body->>'([a-z_]+)'\)::integer", lambda m: f'{ref}."{m.group(1)}"', expr)
    out = out.replace("LEAST(", "min(").replace("GREATEST(", "max(")
    return f"({out})" if out.startswith("SELECT ") else out


def _owners_for_seed(conn, name, body):
    if body.get("business_id") is not None:
        return [body["business_id"]]
    if "seller_business_id" in body:
        return sorted({b for b in (body.get("seller_business_id"), body.get("buyer_business_id")) if b is not None})
    if name in _CHILD:
        parent, fk = _CHILD[name]
        row = conn.execute(text(f'SELECT * FROM "{parent}" WHERE id=:i'), {"i": body.get(fk)}).mappings().first()
        return _owners_for_seed(conn, parent, dict(row)) if row else []
    return []


def pull_feed(db, business_id, cursor, limit):
    from fastapi import HTTPException
    from database.models import SyncFeedEvent
    from database.sync_map import MODEL_MAP
    from database.models import _serialize_orm_obj
    prefix = f"feed:v2:{business_id}:"
    if cursor and not cursor.startswith(prefix):
        # Legacy cursors must replay from zero, never reinterpret a timestamp as
        # an acknowledged revision. UID-keyed apply makes replay idempotent.
        revision = 0
    else:
        try:
            revision = int(cursor[len(prefix):]) if cursor else 0
        except ValueError:
            raise HTTPException(422, "Invalid sync revision")
    rows = db.query(SyncFeedEvent).filter(SyncFeedEvent.business_id == business_id, SyncFeedEvent.revision > revision).order_by(SyncFeedEvent.revision).limit(limit + 1).all()
    more = len(rows) > limit
    rows = rows[:limit]
    changes = {}
    for event in rows:
        model = MODEL_MAP.get(event.entity)
        if model is None:
            raise HTTPException(409, f"Sync entity {event.entity} requires an application upgrade")
        payload = json.loads(event.payload)
        # Current complete rows supply portable parent UID/BizID enrichment.
        # Deleted rows carry their original UID and operation explicitly.
        obj = db.query(model).filter(model.uid == event.row_uid).first() if hasattr(model, "uid") else db.get(model, payload.get("id"))
        if obj is not None:
            payload = _serialize_orm_obj(obj, db)
        elif event.operation == "DELETE":
            payload["_sync_deleted"] = True
        else:
            # A later deletion is represented by a tombstone even if its own
            # event is on the following page.
            payload["_sync_deleted"] = True
        payload["_sync_revision"] = event.revision
        changes.setdefault(event.entity, []).append(payload)
    return {"protocol": 2, "cursor": prefix + str(rows[-1].revision if rows else revision), "changes": changes, "has_more": more, "truncated_tables": [], "failed_tables": [], "pulled_at": None}


def register_metadata_hook(metadata):
    from sqlalchemy import event
    def capture_new_schema(_metadata, connection, **kw):
        # Repeated create_all(checkfirst=True) with no new tables is not a
        # migration. Avoid rewriting every trigger on ordinary test/app probes.
        if kw.get("tables"):
            install_change_feed(connection)
    event.listen(metadata, "after_create", capture_new_schema)
