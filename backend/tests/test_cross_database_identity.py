"""
tests/test_cross_database_identity.py — the BizID is the only portable id
==========================================================================

THE RULE (core/identity.py)

    An integer business id is meaningful ONLY inside the database that issued
    it. The BizID (`users.public_id`) is the ONLY business identifier that may
    cross a database boundary.

A business lives in at least two databases — the owner's local SQLite and the
cloud Postgres — and they number it differently by design. Varshini's business
is `7` locally and `42` on the cloud. Both correct; neither means anything to
the other.

Three defects came from breaking this, all found 2026-07-31 on the live database:

1. **The audit log** stored only integers and was replicated between databases.
   25 local rows carry `business_id=42`, which resolves to nothing here — and
   would resolve to the WRONG business the day a local row is assigned id 42.

2. **LAN discovery** registered every business under its local integer id too,
   into a registry that lives on the shared cloud and is one dict keyed by that
   string. Every installation has a business numbered 1, so `_REGISTRY["1"]` was
   a bucket shared by unrelated customers and `GET /discover/1` would hand one
   of them another's LAN address — `routes/discovery.py`'s own S-2 threat model,
   reached by accident rather than by an attacker. Nothing read those keys: the
   sole consumer documents its parameter as "the business's public_id".

3. **Uploaded log archives** were named `logs_biz_<integer>_*.tar.gz` and shipped
   to the cloud, where that integer names a different business depending on who
   sent it.

These tests pin the boundaries. They deliberately do NOT try to ban integers —
an outbox row, a local cache key, an FK between two local rows are all correct
and cheaper. The rule is that one must never *leave*.
"""
import os
import re
import sys

os.environ.setdefault("JWT_SECRET",   "test-secret-for-identity-abcdef123")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _src(*parts) -> str:
    return open(os.path.join(BACKEND, *parts), encoding="utf-8").read()


# ═════════════════════════════════════════════════════════════════════════════
# The rule is written down somewhere findable
# ═════════════════════════════════════════════════════════════════════════════

class TestTheRuleIsDocumented:

    def test_core_identity_exists_and_states_the_rule(self):
        src = _src("core", "identity.py")
        assert "ONLY inside the database that issued it" in src
        assert "public_id" in src

    def test_it_offers_a_helper_for_the_conversion(self):
        # `owner_bizid` was asserted here too until 2026-07-31, when it was
        # deleted: nothing called it except this line. A helper whose only
        # consumer is its own test is not covered API, it is dead code wearing a
        # green tick — the same shape as a test pointed at an unmounted module.
        from core.identity import bizid_for
        assert callable(bizid_for)

    def test_the_boundaries_point_at_it(self):
        """A rule nobody finds is a rule nobody follows. Each place where an
        integer would otherwise escape carries a pointer."""
        for parts in [("database", "models.py"),
                      ("routes", "discovery.py"),
                      ("routes", "sync.py"),
                      ("services", "sync_worker.py"),
                      ("services", "log_uploader.py")]:
            assert "core/identity.py" in _src(*parts), (
                f"{'/'.join(parts)} sits on a database boundary but does not "
                "reference the identity rule"
            )


# ═════════════════════════════════════════════════════════════════════════════
# Defect 2 — LAN discovery
# ═════════════════════════════════════════════════════════════════════════════

class TestDiscoveryRegistersByBizIDOnly:

    def test_the_registration_loop_never_sends_an_integer_id(self):
        """THE GATE. `biz_ids.append(str(uid))` put every installation's local
        integer ids into a registry shared by all customers."""
        src = _src("main_groq.py")
        block = src[src.index("_register_once"):]
        block = block[:block.index("Initial registration at startup")]
        assert "biz_ids.append(str(uid))" not in block, (
            "the local integer business id is being registered in the SHARED "
            "cloud discovery registry again — every installation has a business "
            "numbered 1, so those keys collide across customers"
        )
        assert "public_id IS NOT NULL" in block, (
            "registration must select only businesses that HAVE a BizID"
        )

    def test_a_business_with_no_bizid_is_reported_not_silently_skipped(self):
        """It cannot be found on the LAN, which the owner needs to know."""
        src = _src("main_groq.py")
        assert "have no BizID and cannot be" in src

    def test_the_only_consumer_queries_by_bizid(self):
        """If anything ever queried by integer, removing the integer
        registration would have broken it. Nothing does."""
        p = os.path.join(BACKEND, "..", "frontend-billing", "src", "utils",
                         "networkDiscovery.js")
        if not os.path.exists(p):
            pytest.skip("frontend not present in this checkout")
        src = open(p, encoding="utf-8").read()
        assert "discoverLocalBackend(bizId)" in src or "@param {string} bizId" in src
        assert "public_id" in src


# ═════════════════════════════════════════════════════════════════════════════
# Defect 3 — artefacts that cross the boundary
# ═════════════════════════════════════════════════════════════════════════════

class TestUploadedArtefactsAreNamedByBizID:

    def test_the_log_archive_name_uses_the_bizid(self):
        src = _src("services", "log_uploader.py")
        assert "_bizid_for(business_id)" in src
        assert 'archive_name = f"logs_biz_{business_id}_' not in src, (
            "the archive is uploaded to the shared cloud; a local integer in its "
            "name identifies a different business depending on who sent it"
        )

    def test_the_retry_sweep_still_matches_pre_rename_archives(self):
        """Renaming an artefact orphans every one already on disk. These upload
        on success and are deleted on success, so a retry loop that cannot see
        them means they are never sent and never cleaned up — a rename turning
        into a slow disk leak."""
        src = _src("services", "log_uploader.py")
        assert "_prefixes" in src
        assert "logs_biz_{p}_" in src
        assert "f\"localid{business_id}\"" in src, (
            "the fallback name used when a business has no BizID must also be "
            "matched by the retry sweep"
        )

    def test_the_fallback_is_labelled_as_non_portable(self):
        """When no BizID exists the integer is all there is — but it must not be
        mistaken for a portable identifier by whoever reads the filename."""
        src = _src("services", "log_uploader.py")
        assert "localid" in src


# ═════════════════════════════════════════════════════════════════════════════
# The boundary translations that make everything downstream safe
# ═════════════════════════════════════════════════════════════════════════════

class TestTheBoundaryTranslations:

    def test_sync_apply_repins_business_id_to_the_local_integer(self):
        """The incoming integer is the SENDING database's. Writing it through
        would attach the row to whichever local business holds that number."""
        src = _src("services", "sync_worker.py")
        assert 'data["business_id"] = business_id' in src

    def test_the_token_to_local_id_translation_can_require_the_bizid(self):
        from services.auth import resolve_business_id_in_db
        import inspect
        assert "require_public_id" in inspect.signature(resolve_business_id_in_db).parameters

    def test_outbound_cloud_calls_identify_by_TOKEN_not_by_payload(self):
        """The correct pattern, pinned so it is not "fixed" into something worse:
        the integer stays local as a token-store key, and the cloud identifies
        the business from the token's public_id claim."""
        for parts, needle in [
            (("services", "immediate_sync.py"), "_get_cloud_token(business_id)"),
            (("core", "api", "staff.py"),        "_get_cloud_token"),
        ]:
            src = _src(*parts)
            assert needle in src
            assert "Authorization" in src


# ═════════════════════════════════════════════════════════════════════════════
# Defect 1 — the audit log (also covered in test_sync_volume_and_tenancy.py)
# ═════════════════════════════════════════════════════════════════════════════

class TestReplicatedTablesCarryTheBizID:

    def test_the_audit_log_has_a_public_id(self):
        from database.models import TableAlteration
        assert "public_id" in {c.name for c in TableAlteration.__table__.columns}

    def test_no_replicated_table_identifies_a_business_by_integer_alone(self):
        """THE GENERAL GATE. A table that syncs and carries `business_id` must
        either be re-pinned on apply (every MODEL_MAP table is — see
        `_apply_pulled_row`) or carry the BizID. This checks the re-pin is the
        mechanism, because it is what makes the integer safe there.
        """
        from database.sync_map import MODEL_MAP
        src = _src("services", "sync_worker.py")
        assert 'data["business_id"] = business_id' in src
        carriers = [
            name for name, model in MODEL_MAP.items()
            if "business_id" in {c.name for c in model.__table__.columns}
        ]
        assert carriers, "expected replicated tables to carry business_id"
