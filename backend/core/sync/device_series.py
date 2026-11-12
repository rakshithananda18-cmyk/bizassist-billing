"""Independent local databases must not mint the same billing series."""
import json
from uuid import UUID, uuid4


def installation_id():
    from services.process_lock import data_path, file_lock
    path = data_path("installation_id")
    with file_lock(path.with_suffix(".lock")):
        try:
            return str(UUID(path.read_text(encoding="utf-8").strip()))
        except FileNotFoundError:
            value = str(uuid4())
            with path.open("x", encoding="utf-8") as stream:
                stream.write(value)
                stream.flush()
                import os
                os.fsync(stream.fileno())
            return value
        except ValueError:
            raise OSError("The installation identity is unreadable; restore it before registering another billing series") from None


def allocate_namespace(db, business_id, installation):
    from database.models import SyncDeviceNamespace
    from core.billing.sequence import next_number
    from core.sync.tombstones import lock_business
    installation = str(UUID(str(installation)))
    lock_business(db, business_id)
    current = db.query(SyncDeviceNamespace).filter_by(business_id=business_id, installation_id=installation).first()
    if current:
        return current.namespace
    number = int(next_number(db, business_id, "DEVICE").rsplit("-", 1)[1])
    if number >= 36 ** 3:
        raise ValueError("The device billing-series limit has been reached")
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    result = ""
    for _ in range(3):
        result = alphabet[number % 36] + result
        number //= 36
    db.add(SyncDeviceNamespace(business_id=business_id, installation_id=installation, namespace=result))
    db.flush()
    return result


def local_series(db, business_id, series):
    if db.get_bind().dialect.name != "sqlite":
        return series
    from database.models import User
    owner = db.query(User).filter(User.id == business_id).first()
    try:
        settings = json.loads(owner.settings or "{}") if owner else {}
        general = settings.get("general") or {}
        if not isinstance(general, dict):
            raise ValueError("Invalid device settings")
    except (ValueError, TypeError, AttributeError):
        from fastapi import HTTPException
        raise HTTPException(409, "Device settings could not be read. Restore them before issuing a bill.") from None
    namespace = general.get("device_invoice_namespace")
    if not namespace:
        if general.get("hosting_mode") == "hybrid":
            from fastapi import HTTPException
            raise HTTPException(409, "Connect this device once to register its billing series before billing with Local + Cloud.",
                                headers={"X-Sync-State": "device-registration"})
        return series
    namespace = str(namespace)
    import re
    if not re.fullmatch(r"[0-9A-Z]{3}", namespace):
        raise ValueError("Invalid device billing namespace")
    suffix = "-" + namespace
    return series if series.endswith(suffix) else series + suffix


def local_counter_number(db, business_id, number, counter_prefix):
    """Scope a POS draft before issuance, including drafts saved before setup.

    Historical imports do not supply a counter_prefix and keep their issued
    numbers. This only handles a new counter sale's proposed number.
    """
    if not counter_prefix or not number:
        return number
    suffix = local_series(db, business_id, "")
    if not suffix:
        return number
    base, separator, tail = str(number).rpartition("-")
    if separator and tail.isdigit():
        return (base if base.endswith(suffix) else base + suffix) + "-" + tail
    return str(number) if str(number).endswith(suffix) else str(number) + suffix
