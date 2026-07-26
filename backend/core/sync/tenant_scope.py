"""
core/sync/tenant_scope.py — static tenant-scope audit (review finding S-3).
==========================================================================
Enumerates every ORM read in the backend against a table that carries an owner
column, and reports the ones with no owner predicate reachable in the enclosing
function.

WHY THIS IS A MODULE AND NOT A ONE-OFF SCRIPT
---------------------------------------------
S-3 was "no DB-level guard behind the tenant filter on SQLite". Postgres RLS
protects the cloud; a local install is SQLite, where ``business_id`` filtering is
application-only, so a single missing ``.filter(business_id == ...)`` is a
cross-tenant read with nothing underneath to catch it. That used to be tolerable
because desktop installs were effectively single-tenant — but the B2B mirror now
writes a COUNTERPARTY's rows into the local database on purpose, so the local DB
holds more than one business's data by design.

The honest fix for "there is no DB layer to enforce this" is not a bigger audit;
an audit is true on the day it is run. It is to make the absence of a filter a
BUILD FAILURE. This module is the analyser; ``tests/test_tenant_scope.py`` is the
gate. A new unscoped read on a tenant table fails CI with a file and line number.

WHAT IT IS AND IS NOT
---------------------
This is a static, syntactic check, and it is stated as such rather than sold as
proof:

  · Owner columns are read from LIVE SQLAlchemy metadata, so the table list can
    never drift from the models.
  · "Scoped" means an owner column name appears in the query chain, or elsewhere
    in the enclosing function. The second clause is deliberately generous — many
    correct call sites build the filter a line earlier, or pass a pre-scoped
    query in. Generous means FEWER findings, so the number this produces is a
    FLOOR on safety, not a ceiling: everything it flags is worth a human
    decision, and a clean result is not a proof of isolation.
  · It cannot see raw SQL, dynamic ``getattr`` filters, or scoping applied by a
    caller two frames up. Those are what the allow-list is for, with a reason
    attached to each entry.

Cross-tenant reads that are INTENTIONAL (the admin console, global uniqueness
probes) live in ``ALLOWED`` with a written justification. That list is the
deliverable as much as the analyser is: it turns "we think these are fine" into
an enumerated, reviewed set that cannot grow silently.
"""
from __future__ import annotations

import ast
import logging
import os
from typing import Dict, Iterable, List, Optional, Set, Tuple

# Column names that scope a row to one business. ``user_id`` is included because
# several tables (register_shifts, shift_cash_movements, table_alterations) scope
# by operator in addition to business.
logger = logging.getLogger("bizassist.tenant_scope")

OWNER_COLUMNS: Set[str] = {
    "business_id",
    "seller_business_id",
    "buyer_business_id",
    "owner_id",
    "user_id",
}

# Query terminals that actually MATERIALISE rows. `.filter()` alone is lazy and
# harmless; it is `.all()` / `.first()` / `.scalar()` that reads.
READ_TERMINALS: Set[str] = {
    "all", "first", "one", "one_or_none", "scalar", "scalars", "count",
}

# Directories that are application code. Tests, migrations and one-off scripts
# are excluded: alembic runs as the schema owner, and scripts are guarded
# separately (finding F-9).
SCANNED_ROOTS: Tuple[str, ...] = ("core", "routes", "services", "database")
SKIPPED_DIRS: Set[str] = {
    "__pycache__", "venv", "tests", "alembic", "chroma_db", "logs",
    ".pytest_cache", "scripts",
}


# ── Intentional cross-tenant reads ───────────────────────────────────────────
# Key: "<relative path>::<function>::<Model>". Value: why it is correct.
#
# Every entry is a claim that a human checked. Adding one is a review decision;
# that is the whole point of keeping the list here instead of loosening the
# analyser.
ALLOWED: Dict[str, str] = {
    # ── Admin console. Cross-tenant BY DEFINITION: the operator of the platform
    # is looking at the platform. Each is gated by
    # `admin_service.require_admin(current_user["id"], db)` on the first line of
    # the handler body — verified, not assumed.
    "routes/admin.py::get_admin_feedbacks::UserFeedback":
        "Admin console: platform-wide merchant feedback. Gated by require_admin().",
    "routes/admin.py::download_feedback_logs::UserFeedback":
        "Admin console: fetches one feedback's log archive by id. Gated by require_admin().",
    "routes/admin.py::get_admin_table_alterations::TableAlteration":
        "Admin console: platform-wide schema-alteration audit log. Gated by require_admin().",
    "services/admin_service.py::read_audit_log::ActionLog":
        "Admin console: platform-wide action audit log. Callers gate on require_admin().",

    # ── Global uniqueness probes. These MUST be unscoped or they do not do their
    # job: a BizID or an invite code is unique across the whole platform, so a
    # per-business check would happily mint a duplicate. Neither returns data —
    # the result is used only as a boolean "is this string taken".
    "core/connection/utils.py::generate_connection_code::B2BInviteCode":
        "Global uniqueness probe for an invite code. Existence-only; a scoped "
        "check would permit cross-business collisions.",
    # NOTE: `generate_bizid`'s probe against `users` needs no allowance. `users`
    # is the tenant ROOT — it carries no owner column at all — so it is not in
    # the tenant-model set and is never scanned. Recorded here because the
    # distinction is easy to get wrong: "queried without a business filter" and
    # "cross-tenant" are the same thing only for tables that HAVE an owner.

    # ── Redemption by secret. The caller presents an unguessable single-use code;
    # the code IS the authorisation, so the lookup cannot be pre-scoped to the
    # redeemer (the seller is unknown until the row is found).
    "core/connection/service.py::redeem_connection_code::B2BInviteCode":
        "Lookup by single-use secret code — the secret is the authorisation. "
        "Seller identity is a RESULT of this query, so it cannot scope it.",

    # ── Public, deliberately unauthenticated surfaces.
    "routes/public.py::get_public_invoice::Invoice":
        "Public invoice view addressed by an unguessable token/uid, not by "
        "business. Scoping is by secret; see the route's own docstring.",

    # ── Cross-business by construction: B2B rows have TWO owners and these
    # functions resolve them, so the owning ids are outputs, not inputs.
    "core/connection/transfer.py::export_b2b_tables::Invoice":
        "Data-transfer export: scoped by the caller's explicit business filter "
        "list, applied before this call.",
    "core/connection/transfer.py::export_b2b_tables::Product":
        "Data-transfer export: as above.",
    "core/connection/transfer.py::import_b2b_tables::B2BOrder":
        "Importer matching incoming rows on durable `uid`; both owner ids are "
        "remapped by the same bizid mapping afterwards (see M-1).",
    "core/connection/transfer.py::import_b2b_tables::Product":
        "Importer matching on durable `uid` before owner remap.",

    # ── Background jobs with no request-scoped tenant.
    "services/alert_jobs.py::_load_active_configs::AlertConfig":
        "Scheduled job: intentionally iterates EVERY tenant's alert config, "
        "then fans out per business.",

    # ── Barcode resolution. Scoped by the caller; kept explicit here because the
    # filter is assembled conditionally and the analyser cannot follow it.
    "core/catalog/barcode.py::resolve_barcode::Product":
        "business_id filter is assembled in the enclosing scope; see the "
        "function's own scoping block.",
}


class Finding:
    __slots__ = ("file", "line", "func", "model", "owners", "severity")

    def __init__(self, file: str, line: int, func: str, model: str,
                 owners: List[str], severity: str):
        self.file, self.line, self.func = file, line, func
        self.model, self.owners, self.severity = model, owners, severity

    @property
    def key(self) -> str:
        return f"{self.file}::{self.func}::{self.model}"

    def __str__(self) -> str:
        return (f"{self.file}:{self.line} {self.func}() reads {self.model} "
                f"(owner columns: {', '.join(self.owners)}) with no owner "
                f"predicate — {self.severity}")


def tenant_models() -> Dict[str, List[str]]:
    """Model class name → owner columns present on its table, from LIVE mapper
    metadata. Reading the mappers rather than a hand-written list is what stops
    this check from silently going stale when a model gains a table."""
    from database.models import Base
    import database.models  # noqa: F401 — registers the main tables
    import core.models      # noqa: F401 — registers B2B / journal tables

    out: Dict[str, List[str]] = {}
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        if table is None:
            continue
        owners = {c.name for c in table.columns} & OWNER_COLUMNS
        if owners:
            out[mapper.class_.__name__] = sorted(owners)
    return out


def _mentions_owner(node: ast.AST) -> bool:
    """True if any owner column name appears anywhere inside this node.

    Deliberately broad — attribute access, keyword argument, string literal or
    bare name all count. Broad means fewer findings, which keeps the gate about
    real gaps rather than about the shape of a filter expression.
    """
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and n.attr in OWNER_COLUMNS:
            return True
        if isinstance(n, ast.keyword) and n.arg in OWNER_COLUMNS:
            return True
        if isinstance(n, ast.Name) and n.id in OWNER_COLUMNS:
            return True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) \
                and n.value in OWNER_COLUMNS:
            return True
    return False


def _query_root(call: ast.Call) -> Tuple[Optional[ast.Call], Optional[str]]:
    """Walk a method chain down to its ``.query(Model)`` root."""
    cur: ast.AST = call
    while isinstance(cur, ast.Call):
        func = cur.func
        if isinstance(func, ast.Attribute) and func.attr == "query" and cur.args:
            arg = cur.args[0]
            if isinstance(arg, ast.Name):
                return cur, arg.id
            if isinstance(arg, ast.Attribute):
                return cur, arg.attr
            return cur, None
        if isinstance(func, ast.Attribute):
            cur = func.value
        else:
            return None, None
    return None, None


def scan(backend_dir: str,
         models: Optional[Dict[str, List[str]]] = None,
         unparsed: Optional[List[str]] = None) -> Tuple[List[Finding], int]:
    """Return (findings, reads_scanned). Findings exclude ``ALLOWED`` entries.

    ``unparsed`` — pass a list to receive the files this scan could NOT read.
    That list is not diagnostics; it is part of the result, and the gate fails on
    it. Originally this function did ``except (SyntaxError, UnicodeDecodeError):
    continue``, which meant **a file the analyser could not parse got a silent
    free pass on tenant scoping** — a hole in a security gate, reported as a
    clean run. That is the exact failure mode this module exists to prevent, so
    an unreadable file is now surfaced rather than skipped (architecture rule 13:
    a swallow is judged by what it protects).
    """
    models = models if models is not None else tenant_models()
    findings: List[Finding] = []
    scanned = 0
    unparsed = unparsed if unparsed is not None else []

    for root, dirs, files in os.walk(backend_dir):
        dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, backend_dir).replace(os.sep, "/")
            if not rel.startswith(SCANNED_ROOTS):
                continue
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError, OSError) as e:
                unparsed.append(f"{rel}: {type(e).__name__}: {e}")
                logger.error(
                    "[S-3] could not parse %s (%s) — it is NOT covered by the "
                    "tenant-scope check and must not be assumed safe", rel, e)
                continue

            for fnode in ast.walk(tree):
                if not isinstance(fnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                func_scoped = _mentions_owner(fnode)
                for n in ast.walk(fnode):
                    if not isinstance(n, ast.Call):
                        continue
                    f = n.func
                    if not (isinstance(f, ast.Attribute) and f.attr in READ_TERMINALS):
                        continue
                    qcall, model = _query_root(n)
                    if qcall is None or model is None or model not in models:
                        continue
                    scanned += 1
                    if _mentions_owner(n) or func_scoped:
                        continue
                    finding = Finding(rel, n.lineno, fnode.name, model,
                                      models[model], "no owner predicate in "
                                      "the chain or the enclosing function")
                    if finding.key in ALLOWED:
                        continue
                    findings.append(finding)

    return findings, scanned


def unused_allowances(backend_dir: str) -> Set[str]:
    """ALLOWED keys that no longer match any read.

    A stale allowance is not harmless: it is a documented exception to a
    security rule for code that has moved or been deleted, and the next reader
    will trust it. Reported so the list stays honest.
    """
    models = tenant_models()
    seen: Set[str] = set()

    for root, dirs, files in os.walk(backend_dir):
        dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS]
        for name in files:
            if not name.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(root, name),
                                  backend_dir).replace(os.sep, "/")
            if not rel.startswith(SCANNED_ROOTS):
                continue
            try:
                tree = ast.parse(open(os.path.join(root, name),
                                      encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError, OSError) as e:
                # Reported, not swallowed: a file we cannot read might contain
                # the read an allowance refers to, and calling that allowance
                # "stale" on the strength of a parse failure would delete a
                # reviewed security exception for the wrong reason.
                logger.error("[S-3] could not parse %s while checking the "
                             "allow-list (%s)", name, e)
                continue
            for fnode in ast.walk(tree):
                if not isinstance(fnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for n in ast.walk(fnode):
                    if not isinstance(n, ast.Call):
                        continue
                    f = n.func
                    if not (isinstance(f, ast.Attribute) and f.attr in READ_TERMINALS):
                        continue
                    _, model = _query_root(n)
                    if model in models:
                        seen.add(f"{rel}::{fnode.name}::{model}")

    return set(ALLOWED) - seen


def format_report(findings: Iterable[Finding], scanned: int,
                  unparsed: Optional[List[str]] = None) -> str:
    findings = list(findings)
    lines = [f"tenant-scope scan: {scanned} tenant-table reads examined, "
             f"{len(findings)} unscoped"]
    for f in findings:
        lines.append(f"  · {f}")
    if unparsed:
        lines.append(f"  !! {len(unparsed)} file(s) could NOT be parsed and are "
                     f"therefore UNCHECKED:")
        for u in unparsed:
            lines.append(f"     · {u}")
    return "\n".join(lines)
