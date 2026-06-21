"""core.templates — the Business Template System (config-per-vertical)."""
from core.templates.loader import (  # noqa: F401
    list_templates, get_template, resolve_for, validate_overrides,
    attributes_schema, clear_cache, FALLBACK_KEY,
)
