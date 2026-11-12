"""Commit-ordered replication, captured by database triggers (including raw SQL).

Every writer increments a per-business clock under a row lock held to commit.
Consequently revision N+1 cannot become visible before N commits or rolls back.
SQLite's single writer gives the same guarantee. No wall clock is a cursor.
"""
from __future__ import annotations
import json
import logging
import random
import re
import time
from sqlalchemy import text, inspect

logger = logging.getLogger("bizassist.change_feed")
_FEED_LOCK_TIMEOUT = "5s"
_sleep = time.sleep


def _sqlstate(exc):
    original = getattr(exc, "orig", exc)
    return getattr(original, "pgcode", None) or getattr(original, "sqlstate", None)


def _change_feed_installed(connection):
    if not connection.execute(text("SELECT to_regprocedure('bizassist_feed_emit(integer,text,jsonb,text)')")).scalar():
        return False
    for name in _sources(connection):
        if not connection.execute(text("SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass(:t) AND tgname='bizassist_feed_capture' AND tgfoid=to_regprocedure(:f) AND tgtype=31 AND tgenabled IN ('O','A') AND NOT tgisinternal"), {"t": name, "f": f"bizassist_feed_{name}()"}).first():
            return False
        cols = {c["name"] for c in inspect(connection).get_columns(name)}
        # Existing capture triggers alone are insufficient proof: the failed
        # attempt may have deadlocked halfway through historical backfill.
        for expr in dict.fromkeys(_owner_expressions(name, cols)):
            missing = connection.execute(text(f'''SELECT EXISTS (
                SELECT 1 FROM (SELECT to_jsonb(t) AS body FROM "{name}" t) s
                WHERE ({expr}) IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM sync_feed_events e WHERE e.business_id=({expr})
                    AND e.entity=:entity AND e.row_uid=COALESCE(s.body->>'uid',s.body->>'id'))
            )'''), {"entity": name}).scalar()
            if missing:
                return False
    return True


def _pg_function(connection, name, signature, returns, body):
    previous = connection.execute(text("SELECT prosrc FROM pg_proc WHERE oid=to_regprocedure(:s)"), {"s": signature}).scalar()
    if re.sub(r"\s+", " ", previous or "").strip() != re.sub(r"\s+", " ", body).strip():
        args = "bid integer, ent text, body jsonb, op text" if name == "bizassist_feed_emit" else ""
        connection.execute(text(f"CREATE OR REPLACE FUNCTION {name}({args}) RETURNS {returns} LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$ {body} $$"))
    connection.execute(text(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC"))


def _sources(connection):
    from database.sync_map import MODEL_MAP
    present = set(inspect(connection).get_table_names())
    return {name: model for name, model in MODEL_MAP.items() if name in present}


def _install_change_feed(connection):
    """Install/refresh triggers and backfill existing rows exactly once per UID.

    Called inside the schema owner's transaction, never by an HTTP app role.
    Trigger writes are fail-closed: a business mutation cannot commit without
    its event. Existing records are seeded while the same writer locks apply.
    """
    from database.models import SyncFeedClock, SyncFeedEvent, SyncTombstone
    SyncFeedClock.__table__.create(connection, checkfirst=True)
    SyncFeedEvent.__table__.create(connection, checkfirst=True)
    SyncTombstone.__table__.create(connection, checkfirst=True)
    from database.sync_map import APPEND_ONLY_DELETE_BLOCKLIST
    retained = ",".join("'" + name + "'" for name in sorted(APPEND_ONLY_DELETE_BLOCKLIST))
    pg = connection.dialect.name == "postgresql"
    if pg:
        connection.execute(text(f"SET LOCAL lock_timeout = '{_FEED_LOCK_TIMEOUT}'"))
        _pg_function(connection, "bizassist_feed_emit", "bizassist_feed_emit(integer,text,jsonb,text)", "void", f"""
            DECLARE rev bigint;
            BEGIN
              IF bid IS NULL THEN RETURN; END IF;
              INSERT INTO sync_feed_clock(business_id,revision) VALUES(bid,1)
              ON CONFLICT(business_id) DO UPDATE SET revision=sync_feed_clock.revision+1
              RETURNING revision INTO rev;
              IF op='DELETE' THEN
                body := body || jsonb_build_object('_sync_deleted_at', clock_timestamp() AT TIME ZONE 'UTC');
                IF ent NOT IN ({retained}) THEN
                  INSERT INTO sync_tombstones(business_id,entity,row_uid,deleted_at,needs_upload)
                  VALUES(bid,ent,COALESCE(body->>'uid',body->>'id'),(body->>'_sync_deleted_at')::timestamp,false)
                  ON CONFLICT(business_id,entity,row_uid) DO UPDATE SET
                    deleted_at=GREATEST(sync_tombstones.deleted_at,EXCLUDED.deleted_at);
                END IF;
              END IF;
              INSERT INTO sync_feed_events(business_id,revision,entity,row_uid,operation,payload)
              VALUES(bid,rev,ent,COALESCE(body->>'uid',body->>'id'),op,body::text);
            END;
        """)
    for name, model in sorted(_sources(connection).items(), key=lambda x: x[0]):
        cols = {c["name"] for c in inspect(connection).get_columns(name)}
        owner_sql = _owner_expressions(name, cols)
        if not owner_sql:
            raise RuntimeError(f"No change-feed ownership rule for {name}")
        if pg:
            calls = " ".join(f"PERFORM bizassist_feed_emit(({expr}),TG_TABLE_NAME,body,TG_OP);" for expr in owner_sql)
            _pg_function(connection, f"bizassist_feed_{name}", f"bizassist_feed_{name}()", "trigger", f"""
                DECLARE body jsonb;
                BEGIN
                  body := CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
                  {calls}
                  RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
                END;
            """)
            correct = connection.execute(text("SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass(:t) AND tgname='bizassist_feed_capture' AND tgfoid=to_regprocedure(:f) AND tgtype=31 AND tgenabled='O'"), {"t":name,"f":f"bizassist_feed_{name}()"}).first()
            if not correct:
                version = int(connection.execute(text("SHOW server_version_num")).scalar())
                if version < 140000:
                    connection.execute(text(f'DROP TRIGGER IF EXISTS bizassist_feed_capture ON "{name}"'))
                replace = "OR REPLACE " if version >= 140000 else ""
                connection.execute(text(f'CREATE {replace}TRIGGER bizassist_feed_capture BEFORE INSERT OR UPDATE OR DELETE ON "{name}" FOR EACH ROW EXECUTE FUNCTION bizassist_feed_{name}()'))
            # BEFORE INSERT does not see an ORM-generated id when the PK is
            # server-generated? PostgreSQL defaults are assigned before this
            # trigger, while UID defaults are assigned by SQLAlchemy before SQL.
        else:
            for op in ("INSERT", "UPDATE", "DELETE"):
                ref = "OLD" if op == "DELETE" else "NEW"
                body = "json_object(" + ",".join(f"'{c}',{ref}.\"{c}\"" for c in sorted(cols)) + ")"
                if op == "DELETE":
                    body = f"json_set({body}, '$._sync_deleted_at', strftime('%Y-%m-%d %H:%M:%f','now'))"
                statements = []
                for expr in owner_sql:
                    bid = _sqlite_owner(expr, ref)
                    statements += [
                        f"INSERT INTO sync_feed_clock(business_id,revision) SELECT {bid},0 WHERE {bid} IS NOT NULL ON CONFLICT(business_id) DO NOTHING;",
                        f"UPDATE sync_feed_clock SET revision=revision+1 WHERE business_id={bid};",
                        f"INSERT INTO sync_feed_events(business_id,revision,entity,row_uid,operation,payload) SELECT {bid},revision,'{name}',CAST(COALESCE(json_extract({body},'$.uid'),json_extract({body},'$.id')) AS TEXT),'{op}',{body} FROM sync_feed_clock WHERE business_id={bid};",
                    ]
                    if op == "DELETE" and name not in APPEND_ONLY_DELETE_BLOCKLIST:
                        statements += [
                            f"INSERT INTO sync_tombstones(business_id,entity,row_uid,deleted_at,needs_upload) "
                            f"SELECT {bid},'{name}',CAST(COALESCE(json_extract({body},'$.uid'),json_extract({body},'$.id')) AS TEXT),"
                            f"strftime('%Y-%m-%d %H:%M:%f','now'),1 WHERE {bid} IS NOT NULL "
                            "ON CONFLICT(business_id,entity,row_uid) DO UPDATE SET deleted_at=max(sync_tombstones.deleted_at,excluded.deleted_at),needs_upload=1;"
                        ]
                trigger = f"bizassist_feed_{name}_{op.lower()}"
                timing = "BEFORE" if op == "DELETE" else "AFTER"
                connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS "{trigger}"')
                connection.exec_driver_sql(f'CREATE TRIGGER "{trigger}" {timing} {op} ON "{name}" BEGIN ' + " ".join(statements) + " END")
        # Seed records absent from the event history; the owner migration holds
        # the global DDL lock and the clock row locks until this transaction ends.
        if pg:
            for expr in dict.fromkeys(owner_sql):
                connection.execute(text(f'''SELECT bizassist_feed_emit(({expr}), :entity, s.body, 'INSERT')
                    FROM (SELECT to_jsonb(t) AS body, t.id AS _id FROM "{name}" t) s
                    WHERE ({expr}) IS NOT NULL AND NOT EXISTS (
                        SELECT 1 FROM sync_feed_events e WHERE e.business_id=({expr}) AND e.entity=:entity
                        AND e.row_uid=COALESCE(s.body->>'uid',s.body->>'id')) ORDER BY s._id'''), {"entity":name})
            continue
        existing = set(connection.execute(text("SELECT business_id,row_uid FROM sync_feed_events WHERE entity=:e"), {"e":name}).all())
        parent_rows = {}
        if name in _CHILD:
            parent, fk = _CHILD[name]
            parent_rows = {r['id']: dict(r) for r in connection.execute(text(f'SELECT * FROM "{parent}"')).mappings()}
        rows = connection.execute(text(f'SELECT * FROM "{name}" ORDER BY id')).mappings().all()
        for row in rows:
            body = dict(row)
            uid = str(body.get("uid") or body.get("id"))
            owner_body = parent_rows.get(body.get(_CHILD[name][1]), {}) if name in _CHILD else body
            owners = ([owner_body['business_id']] if owner_body.get('business_id') is not None else sorted({owner_body[k] for k in ('seller_business_id','buyer_business_id') if owner_body.get(k) is not None}))
            for bid in owners:
                if (bid, uid) in existing:
                    continue
                existing.add((bid, uid))
                encoded = json.dumps(body, default=lambda x: x.isoformat() if hasattr(x, "isoformat") else str(x))
                if pg:
                    connection.execute(text("SELECT bizassist_feed_emit(:b,:e,CAST(:p AS jsonb),'INSERT')"), {"b": bid, "e": name, "p": encoded})
                else:
                    connection.execute(text("INSERT INTO sync_feed_clock(business_id,revision) VALUES(:b,0) ON CONFLICT(business_id) DO NOTHING"), {"b": bid})
                    connection.execute(text("UPDATE sync_feed_clock SET revision=revision+1 WHERE business_id=:b"), {"b": bid})
                    connection.execute(text("INSERT INTO sync_feed_events(business_id,revision,entity,row_uid,operation,payload) SELECT :b,revision,:e,:u,'INSERT',:p FROM sync_feed_clock WHERE business_id=:b"), {"b": bid, "e": name, "u": uid, "p": encoded})


def install_change_feed(connection, **_kw):
    """Retry only genuine PostgreSQL lock conflicts, isolated by savepoints."""
    if connection.dialect.name != "postgresql":
        return _install_change_feed(connection)
    for attempt in range(4):
        try:
            with connection.begin_nested():
                return _install_change_feed(connection)
        except Exception as exc:
            code = _sqlstate(exc)
            if code not in {"40P01", "55P03"}:
                logger.exception("Change-feed installation failed (SQLSTATE %s)", code)
                raise
            if attempt < 3:
                delay = (2 ** (attempt + 1)) + random.uniform(0, 1)
                logger.warning("Change-feed lock conflict %s; retrying in %.1fs", code, delay)
                _sleep(delay)
                continue
            with connection.engine.connect() as probe:
                if _change_feed_installed(probe):
                    logger.warning("Change-feed peer completed after lock conflict %s", code)
                    return
            raise


_CHILD = {"invoice_line_items": ("invoices", "invoice_id"), "purchase_invoice_line_items": ("purchase_invoices", "purchase_invoice_id"), "purchase_order_line_items": ("purchase_orders", "purchase_order_id"), "stock_transfer_line_items": ("stock_transfers", "transfer_id"), "b2b_order_line_items": ("b2b_orders", "order_id"), "shift_cash_movements": ("register_shifts", "shift_id")}


def _owner_expressions(name, cols):
    if "business_id" in cols:
        return ["(body->>'business_id')::integer"]
    if {"seller_business_id", "buyer_business_id"} <= cols:
        # Deterministic lock order for shared records.
        return ["LEAST((body->>'seller_business_id')::integer,(body->>'buyer_business_id')::integer)", "GREATEST((body->>'seller_business_id')::integer,(body->>'buyer_business_id')::integer)"]
    if name in _CHILD:
        parent, fk = _CHILD[name]
        if parent == "b2b_orders":
            # All shared-row writers acquire the two feed clocks in the same
            # order, including children; seller-first can invert parent locks.
            return [f"SELECT {fn}(seller_business_id,buyer_business_id) FROM {parent} WHERE id=(body->>'{fk}')::integer"
                    for fn in ("LEAST", "GREATEST")]
        owners = ("business_id",)
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
            current_body = {column.name: getattr(obj, column.name) for column in model.__table__.columns}
            if business_id not in _owners_for_seed(db, event.entity, current_body):
                # Historical events retain their original owner. A later owner
                # reassignment must never turn that event into a read of the
                # current tenant's private row through its global UID.
                raise HTTPException(409, "Sync row ownership changed; repair is required before this cursor can advance")
            payload = _serialize_orm_obj(obj, db)
        elif event.operation == "DELETE":
            payload["_sync_deleted"] = True
        else:
            # A later deletion is represented by a tombstone even if its own
            # event is on the following page.
            payload["_sync_deleted"] = True
        if payload.get("_sync_deleted"):
            from core.sync.tombstones import get_tombstone
            marker = get_tombstone(db, business_id, event.entity, event.row_uid)
            if marker:
                payload["_sync_deleted_at"] = marker["deleted_at"].isoformat() if hasattr(marker["deleted_at"], "isoformat") else marker["deleted_at"]
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
