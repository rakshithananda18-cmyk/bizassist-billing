from __future__ import annotations
import logging
logger = logging.getLogger('bizassist.security')
"""Narrow authentication bootstrap and explicit service tenant boundaries."""
from sqlalchemy import text, func, or_


def bind_tenant(db, business_id):
    db.info["business_id"] = int(business_id)
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.current_business_id',:b,true)"), {"b": str(int(business_id))})


def service_owner_ids(db):
    if db.bind.dialect.name == "postgresql":
        return list(db.execute(text("SELECT * FROM bizassist_owner_ids()")).scalars())
    from database.models import User
    return [r[0] for r in db.query(User.id).filter(User.parent_business_id.is_(None), or_(User.role.is_(None), func.lower(User.role).notin_(["deleted", "retired"]))).all()]


def _phone(value):
    from services.registration_policy import normalize_phone
    try:
        return normalize_phone(value)
    except ValueError:
        return None


def _identity_filter(User, value):
    clean = (value or "").strip()
    phone = _phone(clean)
    digits = User.phone
    for separator in ("+", " ", "(", ")", "-", "."):
        digits = func.replace(digits, separator, "")
    phone_match = or_(digits == phone[1:], digits == phone[3:] if phone and phone.startswith("+91") else False) if phone else False
    return or_(func.lower(User.username) == clean.lower(), func.lower(User.email) == clean.lower(),
               User.public_id == clean.upper(), phone_match)


def find_owner_by_identifier(db, identifier):
    from database.models import User
    clean = (identifier or "").strip()
    if not clean:
        return None
    if db.bind.dialect.name == "postgresql":
        bid = db.execute(text("SELECT bizassist_owner_identifier(:u)"), {"u": clean}).scalar()
        if bid is None:
            return None
        bind_tenant(db, bid)
        return db.get(User, bid)
    matches = db.query(User).filter(_identity_filter(User, clean), User.parent_business_id.is_(None),
        func.lower(User.role).in_(["enterprise", "owner"])).limit(2).all()
    return matches[0] if len(matches) == 1 else None


def find_user_by_identifier(db, identifier: str):
    """Resolve a unique live identity; a phone fingerprint is never a contact value."""
    from database.models import User
    clean = (identifier or "").strip()
    if not clean:
        return None
    if db.bind.dialect.name == "postgresql":
        row = db.execute(text("SELECT * FROM bizassist_auth_subject(:u,NULL)"), {"u": clean}).first()
        if row is None:
            return None
        bind_tenant(db, row[1])
        return db.get(User, row[0])
    active = or_(User.role.is_(None), func.lower(User.role).notin_(["deleted", "retired"]))
    owners = db.query(User).filter(_identity_filter(User, clean), active, User.parent_business_id.is_(None)).limit(2).all()
    if owners:
        return owners[0] if len(owners) == 1 else None
    matches = db.query(User).filter(_identity_filter(User, clean), active).limit(2).all()
    return matches[0] if len(matches) == 1 else None


def authenticate_identity(db, login, password, owner_login=None):
    from database.models import User
    from services.auth import verify_password
    clean = (login or "").strip()
    owner_clean = owner_login.strip() if owner_login is not None else None
    if not clean or owner_clean == "":
        return None
    row = None
    if db.bind.dialect.name == "postgresql":
        # Never fall back to an unscoped users query after a bootstrap failure.
        row = db.execute(text("SELECT * FROM bizassist_auth_subject(:u,:o)"),
            {"u": clean, "o": owner_clean}).first()
    elif owner_login is not None:
        owner = find_owner_by_identifier(db, owner_login)
        if owner:
            phone = _phone(clean)
            subjects = db.query(User).filter(User.parent_business_id == owner.id,
                or_(func.lower(User.staff_login_name) == clean.lower(), func.lower(User.username) == clean.lower(),
                    User.phone == phone if phone else False),
                or_(User.role.is_(None), func.lower(User.role).notin_(["deleted", "retired"]))).limit(2).all()
            if len(subjects) == 1:
                subject = subjects[0]
                row = (subject.id, owner.id, subject.password, subject.role)
    else:
        subject = find_user_by_identifier(db, clean)
        owner = db.get(User, subject.parent_business_id) if subject and subject.parent_business_id else subject
        if subject and owner and (owner.role or "").lower() not in {"deleted", "retired"}:
            row = (subject.id, subject.parent_business_id or subject.id, subject.password, subject.role)
    if row is None or (row[3] or "").lower() in {"deleted", "retired"} or not verify_password(password, row[2]):
        return None
    bind_tenant(db, row[1])
    return db.get(User, row[0])


def owner_email_exists(db, email, exclude_id=None):
    from database.models import User
    if not email:
        return False
    if db.bind.dialect.name == "postgresql":
        return bool(db.execute(text("SELECT bizassist_owner_email_taken(:e,:i)"), {"e": email, "i": exclude_id}).scalar())
    query = db.query(User.id).filter(func.lower(User.email) == email.lower(), User.parent_business_id.is_(None),
        or_(User.role.is_(None), func.lower(User.role).notin_(["deleted", "retired"])))
    if exclude_id is not None:
        query = query.filter(User.id != exclude_id)
    return query.first() is not None


def username_exists(db, username):
    if db.bind.dialect.name == "postgresql":
        return bool(db.execute(text("SELECT bizassist_username_taken(:u)"), {"u": username}).scalar())
    from database.models import User
    return db.query(User.id).filter(User.username == username).first() is not None


def allocate_owner_id(db):
    if db.bind.dialect.name != "postgresql":
        return None
    value = db.execute(text("SELECT nextval(pg_get_serial_sequence('users','id'))")).scalar()
    bind_tenant(db, value)
    return value


def public_invoice_tenant(db, token):
    if db.bind.dialect.name == "postgresql":
        bid = db.execute(text("SELECT bizassist_public_subject(:t)"), {"t": token}).scalar()
    else:
        from database.models import Invoice
        row = db.query(Invoice.business_id).filter(Invoice.uid_token == token).first()
        bid = row[0] if row else None
    if bid is not None:
        bind_tenant(db, bid)
    return bid


def subject_version(db, user_id):
    if db.bind.dialect.name == "postgresql":
        return db.execute(text("SELECT * FROM bizassist_live_subject(:i)"), {"i": user_id}).first()
    from database.models import User
    user = db.get(User, user_id)
    owner = db.get(User, user.parent_business_id) if user and user.parent_business_id else user
    if user is None or (user.role or "").lower() in {"deleted", "retired"} or owner is None or (owner.role or "").lower() in {"deleted", "retired"}:
        return None
    return (user.token_version or 0,)


def install_security(connection, runtime_role=None):
    """Run with migration credentials, never with the HTTP runtime role.

    The NOLOGIN bootstrap role can read only users/invoices. Only fixed,
    parameterized functions are exposed to the configured runtime role; no SQL
    fragments or tenant setting are accepted from HTTP bootstrap callers.
    """
    if connection.dialect.name != "postgresql":
        return
    import os, re
    runtime_role = runtime_role or os.environ.get("BIZASSIST_RUNTIME_DB_ROLE")
    if runtime_role in {"anon", "authenticated"}:
        raise ValueError("Runtime role must be a private backend role, not a public API role")
    operator, superuser, bypass_rls, create_role = connection.execute(text(
        "SELECT current_user,rolsuper,rolbypassrls,rolcreaterole FROM pg_roles WHERE rolname=current_user"
    )).one()
    if not superuser and not (bypass_rls and create_role):
        raise ValueError("Security installation requires a schema operator with BYPASSRLS and CREATEROLE")
    quoted_operator = connection.dialect.identifier_preparer.quote_identifier(operator)
    connection.exec_driver_sql("""
      DO $$ BEGIN
        IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='bizassist_bootstrap') THEN
          CREATE ROLE bizassist_bootstrap NOLOGIN BYPASSRLS;
        END IF;
      END $$;
      REVOKE CREATE ON SCHEMA public FROM PUBLIC;
    """)
    if not superuser:
        # PostgreSQL 16 gives a role creator ADMIN but not necessarily SET or
        # inherited ownership rights. Both are needed: SET for ALTER OWNER and
        # inherited owner rights for later CREATE OR REPLACE installations.
        # Only the already privileged schema operator receives membership.
        connection.exec_driver_sql(
            f"GRANT bizassist_bootstrap TO {quoted_operator} WITH INHERIT TRUE, SET TRUE"
        )
    # ALTER FUNCTION OWNER requires CREATE on the containing schema for its
    # new owner, even though this NOLOGIN role never creates arbitrary objects.
    # Revoke it below in the same migration transaction after ownership moves.
    connection.exec_driver_sql("GRANT USAGE,CREATE ON SCHEMA public TO bizassist_bootstrap")
    connection.exec_driver_sql(r"""
      GRANT SELECT ON users,invoices TO bizassist_bootstrap;
      GRANT UPDATE(id) ON users TO bizassist_bootstrap;
      GRANT SELECT ON business_settings TO bizassist_bootstrap;
      CREATE OR REPLACE FUNCTION bizassist_phone_identity(value text) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=public,pg_temp AS $$
        SELECT CASE WHEN trim(value) ~ '^\+?[0-9 ()\.\-]+$'
          AND length(regexp_replace(value,'\D','','g')) BETWEEN 8 AND 15
          AND left(regexp_replace(value,'\D','','g'),1)<>'0'
          THEN CASE WHEN left(trim(value),1)<>'+' AND length(regexp_replace(value,'\D','','g'))=10
            THEN '91'||regexp_replace(value,'\D','','g') ELSE regexp_replace(value,'\D','','g') END ELSE NULL END
      $$;
      CREATE OR REPLACE FUNCTION bizassist_owner_identifier(login text) RETURNS integer
      LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        WITH matches AS (
          SELECT id FROM users WHERE parent_business_id IS NULL AND lower(COALESCE(role,'')) IN ('enterprise','owner')
          AND (lower(username)=lower(trim(login)) OR lower(COALESCE(email,''))=lower(trim(login)) OR public_id=upper(trim(login))
            OR (bizassist_phone_identity(login) IS NOT NULL AND bizassist_phone_identity(phone)=bizassist_phone_identity(login)))
        ) SELECT min(id) FROM matches HAVING count(*)=1
      $$;
      CREATE OR REPLACE FUNCTION bizassist_owner_email_taken(value text, except_id integer DEFAULT NULL) RETURNS boolean
      LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        SELECT EXISTS(SELECT 1 FROM users WHERE parent_business_id IS NULL AND lower(COALESCE(role,'')) NOT IN ('deleted','retired')
          AND lower(email)=lower(trim(value)) AND (except_id IS NULL OR id<>except_id))
      $$;
      CREATE OR REPLACE FUNCTION bizassist_google_owner(subject text, verified_email text) RETURNS integer
      LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        WITH owners AS (SELECT id,google_id,email FROM users WHERE parent_business_id IS NULL AND lower(COALESCE(role,'')) IN ('enterprise','owner')),
        linked AS (SELECT id,parent_business_id,role FROM users WHERE NULLIF(subject,'') IS NOT NULL AND google_id=subject),
        email_matches AS (SELECT * FROM owners WHERE verified_email IS NOT NULL AND lower(email)=lower(verified_email))
        SELECT CASE WHEN (SELECT count(*) FROM linked)=1 THEN COALESCE((SELECT id FROM linked WHERE parent_business_id IS NULL AND lower(role) IN ('enterprise','owner')),-1)
          WHEN EXISTS(SELECT 1 FROM linked) THEN -1
          WHEN (SELECT count(*) FROM email_matches)=1 THEN COALESCE((SELECT id FROM email_matches WHERE NULLIF(google_id,'') IS NULL),-1)
          WHEN EXISTS(SELECT 1 FROM email_matches) THEN -1 ELSE NULL END
      $$;
      CREATE OR REPLACE FUNCTION bizassist_auth_subject(login text, owner_login text DEFAULT NULL)
      RETURNS TABLE(subject_id integer,business_id integer,password_hash text,role text)
      LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        WITH matches AS (
          SELECT u.id,COALESCE(u.parent_business_id,u.id) AS bid,u.password,u.role
          FROM users u JOIN users o ON o.id=COALESCE(u.parent_business_id,u.id)
          WHERE lower(COALESCE(u.role,'')) NOT IN ('deleted','retired') AND lower(COALESCE(o.role,'')) NOT IN ('deleted','retired') AND
           ((owner_login IS NULL AND (lower(u.username)=lower(trim(login)) OR lower(COALESCE(u.email,''))=lower(trim(login)) OR u.public_id=upper(trim(login))
               OR (bizassist_phone_identity(login) IS NOT NULL AND bizassist_phone_identity(u.phone)=bizassist_phone_identity(login)))) OR
            (owner_login IS NOT NULL AND o.id=bizassist_owner_identifier(owner_login) AND u.parent_business_id=o.id
               AND (lower(u.staff_login_name)=lower(trim(login)) OR lower(u.username)=lower(trim(login))
                 OR (bizassist_phone_identity(login) IS NOT NULL AND bizassist_phone_identity(u.phone)=bizassist_phone_identity(login)))))
        ), preferred AS (
          SELECT * FROM matches WHERE owner_login IS NOT NULL OR id=bid OR NOT EXISTS(SELECT 1 FROM matches WHERE id=bid)
        ) SELECT id,bid,password,role FROM preferred WHERE (SELECT count(*) FROM preferred)=1
      $$;
      CREATE OR REPLACE FUNCTION bizassist_live_subject(subject integer)
      RETURNS TABLE(token_version integer) LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        SELECT COALESCE(u.token_version,0) FROM users u JOIN users o ON o.id=COALESCE(u.parent_business_id,u.id)
        WHERE u.id=subject AND lower(COALESCE(u.role,'')) NOT IN ('deleted','retired') AND lower(COALESCE(o.role,'')) NOT IN ('deleted','retired')
      $$;
      CREATE OR REPLACE FUNCTION bizassist_username_taken(login text) RETURNS boolean
      LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$ SELECT EXISTS(SELECT 1 FROM users WHERE username=login) $$;
      CREATE OR REPLACE FUNCTION bizassist_public_subject(token text) RETURNS integer
      LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$ SELECT business_id FROM invoices WHERE uid_token=token LIMIT 1 $$;
      CREATE OR REPLACE FUNCTION bizassist_owner_ids() RETURNS SETOF integer
      LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$ SELECT id FROM users WHERE parent_business_id IS NULL AND lower(COALESCE(role,'')) NOT IN ('deleted','retired') $$;
      CREATE OR REPLACE FUNCTION bizassist_public_id_taken(code text) RETURNS boolean
      LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$ SELECT EXISTS(SELECT 1 FROM users WHERE public_id=code) $$;
      CREATE OR REPLACE FUNCTION bizassist_network_state(party integer) RETURNS jsonb
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        DECLARE cfg jsonb; mode text; kind text;
        BEGIN
          IF NOT EXISTS(SELECT 1 FROM users WHERE id=nullif(current_setting('app.current_business_id',true),'')::integer
            AND lower(COALESCE(role,'')) NOT IN ('deleted','retired')) THEN RETURN NULL; END IF;
          BEGIN SELECT settings::jsonb INTO cfg FROM users WHERE id=party; EXCEPTION WHEN invalid_text_representation THEN cfg:='{}'::jsonb; END;
          mode:=COALESCE(cfg->'general'->>'hosting_mode','local');
          SELECT template_key INTO kind FROM business_settings WHERE business_id=party LIMIT 1;
          RETURN jsonb_build_object('hosting_mode',CASE WHEN mode IN ('cloud','hybrid') THEN mode ELSE 'local' END,'business_type',COALESCE(kind,'general'));
        END $$;
      CREATE OR REPLACE FUNCTION bizassist_trade_policy(party integer) RETURNS jsonb
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        DECLARE cfg jsonb;
        BEGIN
          SELECT COALESCE(settings,'{}')::jsonb INTO cfg FROM users WHERE id=party;
          IF cfg IS NULL THEN RAISE EXCEPTION 'Business policy not found'; END IF;
          RETURN jsonb_build_object('round_off_enabled',COALESCE((cfg->'transactions'->>'round_off_enabled')::boolean,true),
            'prevent_negative_stock',COALESCE((cfg->'transactions'->>'prevent_negative_stock')::boolean,false));
        END $$;
      CREATE OR REPLACE FUNCTION bizassist_trade_lock_actor(party integer) RETURNS boolean
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        DECLARE allowed boolean;
        BEGIN
          SELECT parent_business_id IS NULL AND lower(COALESCE(role,'')) NOT IN ('deleted','retired','cashier','supply adder')
          INTO allowed FROM users WHERE id=party FOR UPDATE;
          RETURN COALESCE(allowed,false);
        END $$;
    """)
    signatures = ("bizassist_phone_identity(text)", "bizassist_owner_identifier(text)", "bizassist_owner_email_taken(text,integer)", "bizassist_google_owner(text,text)", "bizassist_auth_subject(text,text)", "bizassist_live_subject(integer)", "bizassist_username_taken(text)", "bizassist_public_subject(text)", "bizassist_owner_ids()", "bizassist_public_id_taken(text)", "bizassist_network_state(integer)", "bizassist_trade_policy(integer)", "bizassist_trade_lock_actor(integer)")
    # Hosted schemas can explicitly grant new functions to public API roles
    # through default privileges. Revoking PUBLIC alone does not remove those
    # grants, or grants retained by CREATE OR REPLACE on existing functions.
    public_api_roles = [name for name in ("anon", "authenticated") if connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": name}).scalar()]
    for signature in signatures:
        connection.exec_driver_sql(f"ALTER FUNCTION {signature} OWNER TO bizassist_bootstrap")
        connection.exec_driver_sql(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        for public_role in public_api_roles:
            connection.exec_driver_sql(f'REVOKE ALL ON FUNCTION {signature} FROM "{public_role}"')
        # Keep existing privileged schema-operator deployments working while
        # HTTP credentials migrate to the separate constrained runtime role.
        connection.exec_driver_sql(f"GRANT EXECUTE ON FUNCTION {signature} TO {quoted_operator}")
    connection.exec_driver_sql("REVOKE CREATE ON SCHEMA public FROM bizassist_bootstrap")
    # Enforce all direct business-owned tables, including later additions.
    from sqlalchemy import inspect
    for table in inspect(connection).get_table_names():
        if table.startswith("ft_"):
            continue  # Field Team owns its separate security migration chain.
        cols = {c["name"] for c in inspect(connection).get_columns(table)}
        bid = "nullif(current_setting('app.current_business_id',true),'')::integer"
        predicate = None
        if table == "users":
            predicate = f"id={bid} OR parent_business_id={bid}"
        elif "business_id" in cols:
            predicate = f"business_id={bid}"
        elif {"seller_business_id", "buyer_business_id"} <= cols:
            predicate = f"seller_business_id={bid} OR buyer_business_id={bid}"
        else:
            from database.change_feed import _CHILD
            children = dict(_CHILD, journal_lines=("journal_entries", "entry_id"), product_barcodes=("products", "product_id"))
            if table in children:
                parent, fk = children[table]
                parentcols = {c["name"] for c in inspect(connection).get_columns(parent)}
                p = f"p.business_id={bid}" if "business_id" in parentcols else f"p.seller_business_id={bid} OR p.buyer_business_id={bid}"
                predicate = f'EXISTS(SELECT 1 FROM "{parent}" p WHERE p.id="{table}"."{fk}" AND ({p}))'
        if predicate:
            connection.exec_driver_sql(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            # Clock/feed are owned by the migration role; their trigger function
            # uses owner rights for the counterparty of shared B2B records.
            if table not in ("sync_feed_clock", "sync_feed_events"):
                connection.exec_driver_sql(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            connection.exec_driver_sql(f'DROP POLICY IF EXISTS app_tenant_boundary ON "{table}"')
            connection.exec_driver_sql(f'CREATE POLICY app_tenant_boundary ON "{table}" AS RESTRICTIVE USING ({predicate}) WITH CHECK ({predicate})')
            # At least one permissive policy is needed for RLS to allow access.
            connection.exec_driver_sql(f'DROP POLICY IF EXISTS app_tenant_allow ON "{table}"')
            connection.exec_driver_sql(f'CREATE POLICY app_tenant_allow ON "{table}" USING ({predicate}) WITH CHECK ({predicate})')
    if runtime_role:
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", runtime_role):
            raise ValueError("Invalid runtime database role")
        role = '"' + runtime_role + '"'
        details = connection.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=:r"), {"r": runtime_role}).first()
        if details is None or any(details):
            raise ValueError("Runtime role must exist and be NOSUPERUSER NOBYPASSRLS")
        connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {role}")
        connection.exec_driver_sql(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {role}")
        connection.exec_driver_sql(f"GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}")
        for signature in signatures:
            if not signature.startswith("bizassist_trade_"):
                connection.exec_driver_sql(f"GRANT EXECUTE ON FUNCTION {signature} TO {role}")
        # Application cannot invent events or alter its acknowledged clocks.
        connection.exec_driver_sql(f"REVOKE INSERT,UPDATE,DELETE ON sync_feed_clock,sync_feed_events FROM {role}")
    # Private platform state has no tenant-owned public API. Supabase's broad
    # default grants must not expose ticket digests or support archives.
    private_tables = ("spent_tickets", "revoked_sessions", "platform_settings", "client_log_archives", "schema_state", "scheduled_job_runs", "discovery_registrations")
    tables = set(inspect(connection).get_table_names())
    for table in private_tables:
        if table not in tables:
            continue
        try:
            connection.exec_driver_sql(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            connection.exec_driver_sql(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        except Exception as exc:
            logger.warning("[Security] RLS enable on %s: %s", table, exc)
        try:
            connection.exec_driver_sql(f'REVOKE ALL ON TABLE "{table}" FROM PUBLIC')
            for public_role in ("anon", "authenticated"):
                if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": public_role}).scalar():
                    connection.exec_driver_sql(f'REVOKE ALL ON TABLE "{table}" FROM "{public_role}"')
            if runtime_role and table != "client_log_archives":
                # These are private service tables, with no tenant-owned row API.
                # The service role alone can access them; public Supabase clients
                # cannot acquire access through a permissive PUBLIC RLS policy.
                connection.exec_driver_sql(f'DROP POLICY IF EXISTS app_service_state ON "{table}"')
                connection.exec_driver_sql(f'CREATE POLICY app_service_state ON "{table}" TO {role} USING (true) WITH CHECK (true)')
        except Exception as exc:
            logger.warning("[Security] Policy update on %s: %s", table, exc)
    if runtime_role and "schema_state" in tables:
        connection.exec_driver_sql(f'REVOKE INSERT,UPDATE,DELETE ON TABLE schema_state FROM {role}')
    trade_role = os.environ.get("BIZASSIST_TRADE_DB_ROLE")
    if trade_role:
        from database.trade_service import install_trade_role
        install_trade_role(connection, trade_role)
    admin_role = os.environ.get("BIZASSIST_ADMIN_DB_ROLE")
    if admin_role:
        from database.admin_service import install_admin_role
        install_admin_role(connection, admin_role)
