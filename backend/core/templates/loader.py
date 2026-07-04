"""
core/templates/loader.py — the Business Template System (Phase 1B centerpiece).
==============================================================================
Config-over-code: ONE JSON template per business type (medical / restaurant /
supermarket / textile / …) defines how the app LOOKS and BEHAVES — labels,
which product fields to show, tax/printing defaults, entry mode, workflows.
The data model never forks: vertical fields ride in `Product.attributes` (JSON)
and the universal columns. Adding a vertical = one JSON file, no migration.

What this module owns (pure, cached, no HTTP):
  list_templates()                 → [{key,label}] for the signup picker
  get_template(key)                → the raw template config (general fallback)
  resolve_for(business_id, db)     → template ⊕ the owner's saved overrides
  validate_overrides(key, ov)      → guardrailed deep-merge candidate (raises)
  attributes_schema(key)           → the `attr:` field schema for form rendering

GUARDRAILS (spec §1.8): templates change PRESENTATION + DEFAULTS only — never the
money math or scoping. Unknown key falls back to `general`. Overrides can flip
behaviour flags / labels but can NEVER introduce a new top-level section or break
GST validity (the route + command still own the deterministic tax math).
"""
import copy
import json
import logging
import os
import sys
from functools import lru_cache
from typing import Optional

logger = logging.getLogger("bizassist.templates")


def _resolve_config_dir() -> str:
    """
    Locate configs/ in BOTH dev and frozen (PyInstaller) runs.

    Dev:     <repo>/backend/core/templates/configs (next to this file).
    Frozen:  PyInstaller puts pure modules inside the bundle archive, so
             __file__ may point somewhere that has no sibling configs/ dir.
             The .spec ships the JSONs as data files at
             <sys._MEIPASS>/core/templates/configs — check there too.
    """
    candidates = [os.path.join(os.path.dirname(__file__), "configs")]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "core", "templates", "configs"))
    # onedir builds: data files live next to the executable
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(os.path.dirname(sys.executable), "core", "templates", "configs"))
        candidates.append(os.path.join(os.path.dirname(sys.executable), "_internal", "core", "templates", "configs"))
    for c in candidates:
        if os.path.isdir(c):
            return c
    logger.error("[TEMPLATE] configs directory not found — tried: %s", candidates)
    return candidates[0]


_CONFIG_DIR = _resolve_config_dir()
FALLBACK_KEY = "general"

# Absolute last resort so the signup picker is never empty (e.g. a packaged
# build that somehow shipped without the config JSONs).
_BUILTIN_FALLBACK_TEMPLATES = (
    {"key": "general", "label": "General / Retail Store"},
)

# Top-level sections an override is allowed to touch. An override may deep-merge
# into these but may NOT add a brand-new top-level key (keeps templates honest).
_MERGEABLE_SECTIONS = frozenset({
    "terminology", "billing", "inventory", "product_fields",
    "invoice_layout", "workflows", "ai_pack", "label",
})


# ── Raw template access (cached) ─────────────────────────────────────────────

@lru_cache(maxsize=None)
def _load_raw(key: str) -> Optional[dict]:
    """Read one <key>.json from configs/. Returns None if the file is absent."""
    path = os.path.join(_CONFIG_DIR, f"{key}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def list_templates() -> tuple:
    """All available templates as a tuple of {key,label} (for the picker).

    Never returns empty: if the configs dir is missing/unreadable (a broken
    packaged build), fall back to the built-in minimal list so the signup
    Business Category dropdown always renders.
    """
    out = []
    try:
        for fname in sorted(os.listdir(_CONFIG_DIR)):
            if not fname.endswith(".json"):
                continue
            cfg = _load_raw(fname[:-5])
            if cfg:
                out.append({"key": cfg["key"], "label": cfg.get("label", cfg["key"])})
    except OSError as e:
        logger.error("[TEMPLATE] cannot list configs dir %s: %s", _CONFIG_DIR, e)
    if not out:
        logger.error("[TEMPLATE] no templates found — serving built-in fallback list")
        out = [dict(t) for t in _BUILTIN_FALLBACK_TEMPLATES]
    return tuple(out)


def get_template(key: Optional[str]) -> dict:
    """
    The raw config for a vertical. Unknown / missing key → `general` fallback
    (spec §1.8). Returns a deep copy so callers can't mutate the cache.
    """
    cfg = _load_raw(key) if key else None
    if cfg is None:
        if key:
            logger.info("[TEMPLATE] unknown key '%s' → falling back to '%s'", key, FALLBACK_KEY)
        cfg = _load_raw(FALLBACK_KEY)
        if cfg is None:
            raise RuntimeError(f"fallback template '{FALLBACK_KEY}.json' is missing")
    return copy.deepcopy(cfg)


# ── Override validation + deep merge ─────────────────────────────────────────

def _deep_merge(base: dict, ov: dict) -> dict:
    """Recursively merge `ov` into a copy of `base` (dicts merge; others replace)."""
    out = copy.deepcopy(base)
    for k, v in ov.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def validate_overrides(key: str, overrides: Optional[dict]) -> dict:
    """
    Validate an owner override blob against the template and return the RESOLVED
    config (template ⊕ overrides). Raises ValueError if the override tries to add
    an unknown top-level section (presentation-only guardrail, §1.8).
    `key` and `label` in the override are ignored for identity (can't rename the
    vertical), but `label` may be customised via the section allowlist.
    """
    template = get_template(key)
    overrides = overrides or {}
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be a JSON object")

    bad = set(overrides.keys()) - _MERGEABLE_SECTIONS - {"key"}
    if bad:
        raise ValueError(f"overrides cannot introduce section(s): {sorted(bad)}")

    clean = {k: v for k, v in overrides.items() if k != "key"}  # identity is fixed
    resolved = _deep_merge(template, clean)
    resolved["key"] = template["key"]                            # never let key drift
    return resolved


# ── Resolution for a specific business (template ⊕ saved overrides) ───────────

def resolve_for(business_id: int, db) -> dict:
    """
    The business's effective config: its chosen template deep-merged with any
    saved overrides in `business_settings`. No row yet → the `general` template.
    This is the frontend's source of truth for labels/fields/defaults.
    """
    # Imported lazily so this module stays importable without the DB layer.
    from core.models import BusinessSettings

    row = (
        db.query(BusinessSettings)
        .filter(BusinessSettings.business_id == business_id)
        .first()
    )
    if row is None:
        return get_template(FALLBACK_KEY)

    overrides = {}
    if row.overrides:
        try:
            overrides = json.loads(row.overrides)
        except (ValueError, TypeError):
            logger.warning("[TEMPLATE] biz %s has unparseable overrides; ignoring", business_id)
            overrides = {}
    try:
        return validate_overrides(row.template_key, overrides)
    except ValueError:
        # Saved overrides somehow invalid — fall back to clean template, don't crash.
        logger.warning("[TEMPLATE] biz %s overrides invalid; using clean template", business_id)
        return get_template(row.template_key)


# ── Form-rendering helper ────────────────────────────────────────────────────

def attributes_schema(key: str) -> list:
    """
    The `attr:`-style product fields for a vertical (the ones that land in
    `Product.attributes` JSON), normalised for the dynamic form:
        [{"attr": "salt", "label": "Salt / Composition", "type": "string",
          "required": False, "options": [...]}]
    Core-column fields (those with `field`) are excluded here — the form renders
    those against real columns.
    """
    template = get_template(key)
    out = []
    for f in template.get("product_fields", []):
        if "attr" not in f:
            continue
        out.append({
            "attr":     f["attr"],
            "label":    f.get("label", f["attr"].replace("_", " ").title()),
            "type":     f.get("type", "string"),
            "required": bool(f.get("required", False)),
            "options":  f.get("options", []),
        })
    return out


def clear_cache() -> None:
    """Drop cached configs (tests / hot-reload after editing a JSON)."""
    _load_raw.cache_clear()
    list_templates.cache_clear()


# ── Billing profiles (plan Phase 2: business-type adaptive counter) ──────────

# Legacy `invoice_layout` strings → viewer template default + paper.
_LAYOUT_TO_TEMPLATE = {
    "thermal_80mm":   {"default_template": "thermal", "paper": "thermal_80mm"},
    "a4_tax_invoice": {"default_template": "classic", "paper": "a4"},
    "a4_service":     {"default_template": "modern",  "paper": "a4"},
}


def get_business_types(row) -> list:
    """Ordered vertical list for a BusinessSettings row. NULL/invalid resolves
    lazily to [template_key] — the no-backfill contract of migration b4e7a2d8f1c3.
    The primary (first entry) always mirrors template_key."""
    types = []
    raw = getattr(row, "business_types", None) if row is not None else None
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                types = [str(t) for t in parsed if _load_raw(str(t))]
        except (ValueError, TypeError):
            types = []
    primary = row.template_key if row is not None else FALLBACK_KEY
    if not types:
        types = [primary]
    if types[0] != primary:                    # primary always leads
        types = [primary] + [t for t in types if t != primary]
    return types


def resolve_billing_profile(business_id: int, db, mode_key: Optional[str] = None) -> dict:
    """
    The RESOLVED billing-counter profile for one business + one counter mode
    (plan §2.1). Presentation + defaults ONLY — the command layer still owns all
    money math. Owner overrides apply to the PRIMARY vertical only (they were
    keyed to it); secondary modes run their clean template config.

        {mode_key, business_types, entry_mode, customer_required,
         default_invoice_type, tax_inclusive_default, payment_modes,
         line_fields, counter_widgets, terminology, inventory,
         invoice: {default_template, paper}}
    """
    from core.models import BusinessSettings

    row = (
        db.query(BusinessSettings)
        .filter(BusinessSettings.business_id == business_id)
        .first()
    )
    types = get_business_types(row)
    mode = mode_key if (mode_key and mode_key in types) else types[0]
    if mode_key and mode_key not in types:
        logger.info("[TEMPLATE] biz %s asked for mode '%s' not in %s → primary '%s'",
                    business_id, mode_key, types, types[0])

    if row is not None and mode == row.template_key:
        cfg = resolve_for(business_id, db)     # primary: template ⊕ overrides
    else:
        cfg = get_template(mode)               # secondary: clean template

    billing = cfg.get("billing", {})
    layout = cfg.get("invoice_layout", "a4_tax_invoice")
    invoice = dict(_LAYOUT_TO_TEMPLATE.get(layout, _LAYOUT_TO_TEMPLATE["a4_tax_invoice"]))

    profile = {
        "mode_key":              cfg.get("key", mode),
        "label":                 cfg.get("label", mode),
        "business_types":        types,
        "entry_mode":            billing.get("entry_mode", "search"),
        "customer_required":     bool(billing.get("customer_required", False)),
        "default_invoice_type":  billing.get("default_invoice_type", "B2C"),
        "tax_inclusive_default": bool(billing.get("tax_inclusive_default", False)),
        "payment_modes":         billing.get("payment_modes", ["cash", "upi", "card"]),
        "allow_returns":         bool(billing.get("allow_returns", True)),
        "line_fields":           billing.get("line_fields", []),
        "counter_widgets":       billing.get("counter_widgets", []),
        "terminology":           cfg.get("terminology", {}),
        "inventory":             cfg.get("inventory", {}),
        "invoice":               invoice,
    }
    logger.info("[TEMPLATE] billing_profile_applied business_id=%s mode_key=%s "
                "business_types=%s entry_mode=%s customer_required=%s",
                business_id, profile["mode_key"], ",".join(types),
                profile["entry_mode"], profile["customer_required"])
    return profile
