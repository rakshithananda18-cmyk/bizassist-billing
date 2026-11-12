"""Compare-and-set JSON updates for concurrent settings writers."""
import copy
import json

from sqlalchemy import select, update
from sqlalchemy.orm.attributes import set_committed_value

_CONSENT_KEYS = ("hosting_mode", "sync_mode_revision", "sync_bootstrap_pending", "device_invoice_namespace", "device_installation_id", "sync_local_only_explicit", "diagnostic_upload_enabled")


def update_settings_atomic(db, user, mutate):
    """Apply a mutation to the current DB value; caller owns the transaction."""
    from database.models import User
    with db.no_autoflush:
        for _ in range(10):
            raw = db.execute(select(User.settings).where(User.id == user.id)).scalar_one()
            current = json.loads(raw or "{}")
            if not isinstance(current, dict):
                raise ValueError("Stored settings must be a JSON object")
            proposed = mutate(copy.deepcopy(current))
            encoded = json.dumps(proposed)
            updated = db.execute(update(User).where(User.id == user.id, User.settings == raw)
                                 .values(settings=encoded).execution_options(synchronize_session=False))
            if updated.rowcount == 1:
                set_committed_value(user, "settings", encoded)
                return proposed
    raise RuntimeError("Settings changed concurrently; retry the update")


def replace_settings_preserving_consent(db, user, proposed):
    """Legacy whole-document writers cannot author device synchronization consent."""
    def merge(current):
        value = copy.deepcopy(proposed)
        general = value.setdefault("general", {})
        stored = current.get("general") or {}
        for key in _CONSENT_KEYS:
            if key in stored:
                general[key] = stored[key]
            else:
                general.pop(key, None)
        return value
    return update_settings_atomic(db, user, merge)
