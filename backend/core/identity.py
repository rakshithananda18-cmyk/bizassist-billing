"""
core/identity.py — which business identifier is valid where.
============================================================

THE ONE RULE
------------
    An integer business id is meaningful ONLY inside the database that issued it.
    The BizID (`users.public_id`, "BA-XXXXXX") is the ONLY business identifier
    that may cross a database boundary.

A business exists in at least two databases at once — the owner's local SQLite
and the cloud Postgres — and they number it differently. This is by design, not
drift: rows are created independently on each side, so their autoincrement ids
cannot agree. Varshini's business is `7` locally and `42` on the cloud. Both are
correct. Neither means anything to the other.

WHAT "CROSSES A BOUNDARY" MEANS
-------------------------------
Anything that is written on one side and read on the other:

  * a payload sent to the cloud, or returned from it;
  * a URL path or query parameter on a cross-backend call;
  * a key in a registry the cloud holds on behalf of many installations;
  * a filename on an artefact that gets uploaded;
  * a column in a table that is replicated by sync.

If a value is only ever written and read inside one database — an outbox row, a
local cache key, an FK between two local rows — the integer is correct and
cheaper. This rule is not "never use integers". It is "never let one leave".

WHAT THIS RULE COST WHEN IT WAS BROKEN
--------------------------------------
Three separate defects, all found on 2026-07-31, all from the same mistake:

1. **The audit log.** `table_alterations` stored `user_id`/`business_id` as
   integers, no BizID, and the table was in the sync map — so it was replicated
   between databases. 25 rows in the local database carry `business_id=42`,
   which resolves to nothing here. Worse: the day a local row is assigned id 42,
   those rows begin reading as *that* business — someone's writes silently
   attributed to the wrong tenant, in the log you would consult to find out who
   did what. Fixed by adding `public_id` and removing the table from sync.

2. **LAN discovery.** The local backend registered each business under BOTH its
   BizID and its local integer id, into a registry that lives on the shared
   cloud and is one dict keyed by that string. Every installation has a business
   numbered 1, so customer A's `_REGISTRY["1"]` and customer B's were the same
   bucket, and `GET /discover/1` would hand one customer the other's LAN
   address. That is the credential-harvesting path `routes/discovery.py`'s own
   threat model (S-2) describes, reached by accident between tenants rather than
   by an attacker. The integer key was never read by anything — the sole
   consumer, `networkDiscovery.discoverLocalBackend(bizId)`, documents its
   parameter as "the business's public_id". Fixed by registering BizID only.

3. **Uploaded log archives.** Named `logs_biz_<integer>_<ts>.tar.gz` and shipped
   to the cloud, where that integer names a different business depending on who
   sent it. Fixed by naming them with the BizID.

THE PATTERN THAT IS CORRECT AND SHOULD NOT BE "FIXED"
-----------------------------------------------------
Most local→cloud calls look like this and are right:

    token = _get_cloud_token(business_id)      # LOCAL integer, local lookup
    httpx.post(f"{CLOUD_URL}/api/...", json=payload,
               headers={"Authorization": f"Bearer {token}"})

The integer never leaves — it is the key to a local token store. The cloud
identifies the business from the TOKEN, which carries the BizID as its
`public_id` claim. Sync push/pull works the same way, and `_apply_pulled_row`
re-pins `data["business_id"] = business_id` to the receiving database's own
integer precisely so a foreign one can never be written.

WHERE THE BizID COMES FROM AT RUNTIME
-------------------------------------
* Request handling: `current_bizid_var` (set by the middleware in `main_groq.py`
  from the token's `public_id` claim).
* Background work: `bizid_for(business_id)` below.
* Tokens: the `public_id` claim, minted in `routes/auth.py`.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("bizassist.identity")


def bizid_for(business_id: int) -> Optional[str]:
    """The BizID for a local integer business id, or None.

    Use this whenever an integer id is about to leave this database — a payload,
    a URL, a filename, a registry key. Returning None means the business has no
    BizID yet, which is a real state (pre-backfill) and must be handled
    explicitly by the caller rather than papered over with the integer.
    """
    try:
        from database.db import SessionLocal
        from database.models import User
        db = SessionLocal()
        try:
            row = (
                db.query(User.public_id)
                .filter(User.id == business_id)
                .first()
            )
            return (row[0] or None) if row else None
        finally:
            db.close()
    except Exception as e:
        logger.warning("[IDENTITY] could not resolve BizID for business_id=%s: %s",
                       business_id, e)
        return None


# NOTE: `owner_bizid(user)` was defined here and deleted 2026-07-31. It
# resolved a User row to its business's BizID, handling the staff case. It was
# speculative API — nothing ever called it except its own test. `bizid_for()`
# above covers every real caller, because they all already hold an OWNER id.
# Re-add it when something needs it, not before.
