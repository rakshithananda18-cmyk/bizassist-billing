"""
tests/test_logging_config.py
============================
Unit tests for the central logging configuration.

Covers:
  - get_logger() namespacing under the shared 'bizassist.' parent
  - configure_logging() installs exactly one handler (idempotent)
  - the component filter strips the 'bizassist.' prefix for display
  - noisy third-party libraries are pinned to WARNING
  - LOG_LEVEL env var is honoured
  - the canonical TAG set is internally consistent
"""
import os
import sys
import logging

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from logging_config import configure_logging, get_logger, TAG, _ComponentFilter, _NOISY_LIBS


def test_get_logger_namespaces_under_bizassist():
    assert get_logger("services.ai_router").name == "bizassist.services.ai_router"
    # __name__ == "__main__" collapses to a stable app logger
    assert get_logger("__main__").name == "bizassist.app"
    # already-namespaced names are left untouched (no double prefix)
    assert get_logger("bizassist.foo").name == "bizassist.foo"


def _our_handlers():
    """Root handlers installed by configure_logging (identified by our filter)."""
    return [
        h for h in logging.getLogger().handlers
        if any(isinstance(f, _ComponentFilter) for f in h.filters)
    ]


def test_configure_logging_is_idempotent(monkeypatch):
    # Hermetic: without LOG_FILE there is exactly one (stream) handler. (With
    # LOG_FILE set a second file handler is added — covered separately below.)
    monkeypatch.delenv("LOG_FILE", raising=False)
    configure_logging()
    first = len(_our_handlers())
    configure_logging()
    second = len(_our_handlers())
    assert first == 1, f"expected exactly one configured handler, got {first}"
    assert second == 1, "re-running configure_logging must not stack handlers"


def test_log_file_adds_one_extra_handler(monkeypatch, tmp_path):
    # When LOG_FILE is set, configure_logging adds a file handler in addition to
    # the stream one — and stays idempotent (no stacking on repeat calls).
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "biz.log"))
    configure_logging()
    first = len(_our_handlers())
    configure_logging()
    second = len(_our_handlers())
    assert first == 2, f"expected stream + file handler, got {first}"
    assert second == 2, "re-running configure_logging must not stack handlers"
    monkeypatch.delenv("LOG_FILE", raising=False)
    configure_logging()  # restore single-handler state for other tests


def test_component_filter_strips_prefix():
    f = _ComponentFilter()
    rec = logging.LogRecord("bizassist.services.ai_router", logging.INFO, __file__, 1, "x", None, None)
    f.filter(rec)
    assert rec.component == "services.ai_router"

    rec_root = logging.LogRecord("bizassist", logging.INFO, __file__, 1, "x", None, None)
    f.filter(rec_root)
    assert rec_root.component == "app"


def test_noisy_libs_pinned_to_warning():
    configure_logging()
    for lib in _NOISY_LIBS:
        assert logging.getLogger(lib).level == logging.WARNING, f"{lib} should be WARNING"


def test_log_level_env_var_honoured(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    configure_logging()
    assert logging.getLogger("bizassist").level == logging.DEBUG
    # restore a sane default for the rest of the suite
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    configure_logging()
    assert logging.getLogger("bizassist").level == logging.INFO


def test_tags_are_unique_and_bracketed():
    tags = [v for k, v in vars(TAG).items() if not k.startswith("_") and isinstance(v, str)]
    assert tags, "TAG class should expose tag constants"
    for t in tags:
        assert t.startswith("[") and t.endswith("]"), f"tag {t} must be [BRACKETED]"
        assert t.upper() == t, f"tag {t} must be UPPERCASE"
    assert len(tags) == len(set(tags)), "tag values must be unique"
