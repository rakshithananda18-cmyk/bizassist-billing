"""Regression coverage for safe production startup seeding."""

from unittest.mock import MagicMock

from database.migration import _seed_users


def test_non_test_seed_never_creates_or_resets_builtin_admin(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./production.db")
    monkeypatch.setenv("BIZASSIST_TESTING", "0")
    monkeypatch.delenv("ADMIN_SEED_PASSWORD", raising=False)

    db = MagicMock()
    db.query.return_value.all.return_value = []

    _seed_users(db)

    db.add.assert_not_called()
    # Existing passwords may still be upgraded to bcrypt below, but bootstrap
    # must neither create a default account nor mutate an existing admin.
    assert not db.query.return_value.filter.called
