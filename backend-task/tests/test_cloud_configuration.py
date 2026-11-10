"""Field operations use Pro and the shared cloud database, never a silent
SQLite fallback when a deployment loses its database configuration."""
import runpy

import pytest

from app import config


def _read(monkeypatch, *, database="postgresql://user:password@invalid.example/task_test", mirror=None, deployed=False):
    monkeypatch.setenv("DATABASE_URL", database)
    monkeypatch.setenv("JWT_SECRET", "configuration-test-secret-0123456789abcdef")
    monkeypatch.setenv("SUBSCRIPTION_ENFORCED", "")
    monkeypatch.setenv("TASK_CREATE_BILLING_MIRROR", mirror or "")
    monkeypatch.setenv("TASK_ALLOW_SQLITE_TESTING", "")
    monkeypatch.setenv("SPACE_ID", "org/test-space" if deployed else "")
    monkeypatch.setenv("K_SERVICE", "")
    monkeypatch.setenv("ENVIRONMENT", "")
    return runpy.run_path(config.__file__)


def test_cloud_field_team_requires_pro_by_default(monkeypatch):
    loaded = _read(monkeypatch)
    assert loaded["REQUIRE_PRO"] is True
    assert loaded["CREATE_BILLING_MIRROR"] is False


def test_implicit_local_fallback_is_refused(monkeypatch):
    with pytest.raises(RuntimeError, match="same cloud PostgreSQL"):
        _read(monkeypatch, database="sqlite:///./unrelated_local.db")


def test_standalone_mirror_requires_explicit_development_opt_in(monkeypatch):
    loaded = _read(monkeypatch, database="sqlite:///./isolated_task_test.db", mirror="1")
    assert loaded["IS_SQLITE"] is True and loaded["CREATE_BILLING_MIRROR"] is True


def test_cloud_host_cannot_start_on_a_local_mirror(monkeypatch):
    with pytest.raises(RuntimeError, match="same cloud PostgreSQL"):
        _read(monkeypatch, database="sqlite:///./isolated_task_test.db", mirror="1", deployed=True)


def test_deployed_field_team_cannot_disable_pro_gate(monkeypatch):
    _read(monkeypatch, deployed=True)
    monkeypatch.setenv("SUBSCRIPTION_ENFORCED", "0")
    assert runpy.run_path(config.__file__)["REQUIRE_PRO"] is True


def test_cloud_host_cannot_create_or_alter_billing_mirror(monkeypatch):
    with pytest.raises(RuntimeError, match="development/test-only"):
        _read(monkeypatch, mirror="1", deployed=True)


def test_explicit_shared_test_schema_does_not_need_a_mirror(monkeypatch):
    monkeypatch.setenv("TASK_ALLOW_SQLITE_TESTING", "1")
    monkeypatch.setenv("TASK_CREATE_BILLING_MIRROR", "0")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./shared_field_test.db")
    monkeypatch.setenv("SPACE_ID", "")
    monkeypatch.setenv("K_SERVICE", "")
    monkeypatch.setenv("ENVIRONMENT", "")
    loaded = runpy.run_path(config.__file__)
    assert loaded["IS_SQLITE"] is True and loaded["CREATE_BILLING_MIRROR"] is False
