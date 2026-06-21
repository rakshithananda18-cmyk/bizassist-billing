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
from functools import lru_cache
from typing import Optional

logger = logging.getLogger("bizassist.templates")

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "configs")
FALLBACK_KEY = "general"

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
    """All available templates as a tuple of {key,label} (for the picker)."""
    out = []
    for fname in sorted(os.listdir(_CONFIG_DIR)):
        if not fname.endswith(".json"):
            continue
        cfg = _load_raw(fname[:-5])
        if cfg:
            out.append({"key": cfg["key"], "label": cfg.get("label", cfg["key"])})
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
