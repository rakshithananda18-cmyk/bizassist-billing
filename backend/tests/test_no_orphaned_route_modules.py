"""
tests/test_no_orphaned_route_modules.py — every route module must be reachable
==============================================================================

THE DEFECT THIS EXISTS TO CATCH
-------------------------------
`tests/test_sync_migration_fixes.py` imported `routes.migrate` and passed for
months. `routes/migrate.py` is not mounted — `main_groq.py` mounts
`routes/data_transfer.py`, and the two declare DIFFERENT paths
(`/api/migrate/*` vs `/api/data-transfer/*`).

So the suite was green about a module that cannot execute, while the module that
DOES execute had lost a protection the dead one still carried
(`_free_invoice_number_on_import`, the M-3 × §9.3b invoice-number guard). A bill
whose number was already held by a different document was silently SKIPPED on
import — a lost sale — and nothing failed.

A test pointed at dead code is worse than no test: it reports confidence about a
path that never runs.

WHAT THIS GATE ASSERTS
----------------------
1. Every module that declares HTTP routes is reachable from `main_groq.py`'s
   router graph, or is explicitly allow-listed with a reason.
2. No test imports a module that is unreachable.

The graph is walked TRANSITIVELY. `core/api/__init__.py` aggregates eighteen
routers into `core_router`, which `main_groq.py` then mounts once — a gate that
only looked at `app.include_router(...)` would report all eighteen as orphans.
That naive version was written first and produced 23 false positives; it is
recorded here because "the check was too crude to be believed, so it got
ignored" is its own failure mode.
"""
import ast
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Modules that declare routes but are deliberately NOT mounted. Every entry
# needs a reason, and ideally a removal date.
ALLOWED_UNMOUNTED = {
    "routes.migrate": (
        "Deprecated predecessor of routes/data_transfer.py, retained for a "
        "cleanup pass. Declares /api/migrate/* which is not served. See "
        "docs/CLEANUP_PLAN_2026-07-31.md §1."
    ),
    # ── Found BY this gate on the day it was written, 2026-07-31 ─────────────
    # Three more predecessors nobody had noticed. Every path each of them
    # declares is also declared by a module that IS mounted, so none of them
    # serves anything. Verified function-by-function — see the cleanup plan §1b.
    "routes.insights": (
        "Superseded by routes/ai_insights.py, which declares all 9 of its paths. "
        "Function comparison: zero unmatched behavioural lines. Pending deletion."
    ),
    "routes.smart_insights": (
        "Superseded by routes/ai_insights.py, which declares both its paths. "
        "Function comparison: zero unmatched behavioural lines. Pending deletion."
    ),
    "routes.sales": (
        "Superseded by core/api/sales.py, which declares all 4 of its paths and "
        "is stricter (require_open_shift vs an optional shift). It also exposes "
        "`uid_token` in invoice responses — the PUBLIC SHARE-LINK secret behind "
        "GET /public/invoice/{uid_token} — which the live module does not. "
        "Pending deletion; do not mount."
    ),
}


def _module_path(mod: str) -> str:
    return os.path.join(BACKEND, mod.replace(".", os.sep) + ".py")


def _read(mod: str) -> str:
    p = _module_path(mod)
    if not os.path.exists(p):
        p = os.path.join(BACKEND, mod.replace(".", os.sep), "__init__.py")
    try:
        return open(p, encoding="utf-8").read()
    except Exception:
        return ""


def _router_aliases(src: str) -> dict:
    """local alias -> module, for `from X import router as Y` (and `a, router as Y`)."""
    out = {}
    for m in re.finditer(r"from\s+([\w.]+)\s+import\s+([^\n#]+)", src):
        mod, names = m.group(1), m.group(2)
        for part in names.split(","):
            part = part.strip().rstrip(")")
            am = re.match(r"(\w+)\s+as\s+(\w+)$", part)
            if am and am.group(1) in ("router", "core_router"):
                out[am.group(2)] = mod
            elif part in ("router", "core_router"):
                out[part] = mod
    return out


def _included(src: str) -> set:
    """Every alias passed to *.include_router(...)."""
    return set(re.findall(r"\.include_router\(\s*(\w+)", src))


def _reachable_modules() -> set:
    """Walk the router graph from main_groq.py, transitively."""
    seen, queue = set(), ["main_groq"]
    while queue:
        mod = queue.pop()
        if mod in seen:
            continue
        seen.add(mod)
        src = _read(mod)
        if not src:
            continue
        aliases = _router_aliases(src)
        for alias in _included(src):
            target = aliases.get(alias)
            if target and target not in seen:
                queue.append(target)
    seen.discard("main_groq")
    return seen


def _route_declaring_modules() -> set:
    """Every module containing an @router.<verb>( decorator."""
    out = set()
    for sub in ("routes", os.path.join("core", "api")):
        d = os.path.join(BACKEND, sub)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith(".py") or fn == "__init__.py":
                continue
            src = open(os.path.join(d, fn), encoding="utf-8").read()
            if re.search(r"@router\.(get|post|put|delete|patch)\(", src):
                out.add(sub.replace(os.sep, ".") + "." + fn[:-3])
    return out


def test_the_graph_walker_finds_the_nested_routers():
    """Guard the gate itself. `core/api/__init__.py` aggregates eighteen routers
    into `core_router`; if the walker stopped at the top level it would report
    all of them as orphans and the whole check would be noise."""
    reachable = _reachable_modules()
    assert "core.api" in reachable, "core_router was not followed"
    for nested in ("core.api.sales", "core.api.reports", "core.api.staff"):
        assert nested in reachable, f"{nested} not reached through core_router"
    assert len(reachable) >= 35, f"only {len(reachable)} modules reached — walker is too shallow"


def test_every_route_module_is_mounted_or_allow_listed():
    """THE GATE. A module declaring routes that nothing mounts is dead weight at
    best, and at worst a second implementation drifting away from the live one —
    which is exactly what routes/migrate.py became."""
    orphans = sorted(_route_declaring_modules() - _reachable_modules() - set(ALLOWED_UNMOUNTED))
    assert not orphans, (
        "these modules declare HTTP routes but nothing mounts them: "
        f"{orphans}. Either mount them, delete them, or add them to "
        "ALLOWED_UNMOUNTED with a reason."
    )


def test_no_test_imports_an_unreachable_module():
    """The actual failure: a suite reporting green for code that cannot run.

    Allow-listing a module for being unmounted does NOT allow tests to keep
    exercising it — that is the whole defect. `test_staff_login_name_unique.py`
    is exempt because it asserts *about* the deprecated module (that nothing
    imports it) rather than exercising it.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    unreachable = set(ALLOWED_UNMOUNTED) | (
        _route_declaring_modules() - _reachable_modules()
    )
    exempt = {"test_staff_login_name_unique.py", "test_no_orphaned_route_modules.py",
              "test_cross_database_identity.py", "test_data_transfer_staff_identity.py"}
    offenders = []
    for fn in sorted(os.listdir(here)):
        if not fn.endswith(".py") or fn in exempt:
            continue
        try:
            tree = ast.parse(open(os.path.join(here, fn), encoding="utf-8").read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in unreachable:
                offenders.append(f"{fn} imports {node.module}")
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in unreachable:
                        offenders.append(f"{fn} imports {a.name}")
    assert not offenders, (
        "these tests exercise modules that are not mounted, so they report green "
        f"for code that cannot run: {offenders}"
    )


def test_the_allow_list_entries_still_exist():
    """An allow-list that outlives its entries silently stops meaning anything."""
    for mod in ALLOWED_UNMOUNTED:
        assert os.path.exists(_module_path(mod)), (
            f"{mod} is allow-listed as unmounted but no longer exists — remove "
            "the entry."
        )


def test_the_allow_list_gives_a_reason():
    for mod, reason in ALLOWED_UNMOUNTED.items():
        assert reason and len(reason) > 30, f"{mod} needs a real reason, not a placeholder"
