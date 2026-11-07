"""Release scripts must agree on runtime isolation and verify before rollout."""
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("filename", ["deploy_cloudrun.sh","deploy_cloudrun.ps1"])
def test_cloud_release_preserves_unmanaged_configuration_and_single_instance(filename):
    script = (ROOT/"backend"/filename).read_text(encoding="utf-8")
    assert "--update-env-vars" in script and "--set-env-vars" not in script
    assert "--update-secrets" in script and "--set-secrets" not in script
    assert re.search(r"--max-instances\s+1\b",script)
    assert "SUBSCRIPTION_ENFORCED=" in script
    assert "CLOUD_RUN_REGION=" in script and "SSE_MAX_STREAM_SECONDS=100" in script
    assert "ADMIN_SERVICE_URL" in script and "BILLING_CRON_SECRET" in script
    assert "--no-traffic" in script and "--tag" in script
    assert "/health" in script and "connected" in script
    assert script.index("--no-traffic") < script.index("run services update-traffic")
    assert "cloud-scheduler-jobs.json" in script
    assert "--update-headers" in script and "--headers" in script
    assert "--time-zone" in script and "Asia/Kolkata" in script
    assert "--attempt-deadline" in script and "120s" in script
    assert "--max-retry-attempts" in script
    for retired_origin in ("https://team.staterbill.com","https://ai.staterbill.com"):
        assert retired_origin not in script


def test_shared_scheduler_manifest_covers_only_supported_jobs():
    entries = json.loads((ROOT/"ops/cloud-scheduler-jobs.json").read_text())
    expected = {"daily_summary","overdue_alerts","low_stock_alerts","expiry_alerts",
                "books_integrity_audit","telemetry_retention","memory_distillation",
                "telemetry_db_maintenance"}
    assert {entry["job"] for entry in entries} == expected
    assert len(entries) == len(expected)
    assert all(len(entry["schedule"].split())==5 for entry in entries)


def test_shell_health_gate_targets_actual_tag_and_checks_database():
    script = (ROOT/"backend/deploy_cloudrun.sh").read_text()
    assert 't.get("tag")=="rc"' in script
    assert 't.get("url", "")' in script
    assert '"${PROBE_URL}/health"' in script
    assert 'd.get("db")=="connected"' in script
    assert 'HEALTH_DEADLINE=$((SECONDS + 120))' in script
    assert 'unset CRON_SECRET' in script and 'set +x' in script
