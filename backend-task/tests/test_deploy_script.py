"""A redeploy keeps secrets configured outside this script."""
from pathlib import Path
import pytest


@pytest.mark.parametrize("filename", ["deploy_cloudrun.ps1", "deploy_cloudrun.sh"])
def test_both_deploy_scripts_keep_custom_and_legacy_field_origins(filename):
    code = (Path(__file__).resolve().parents[1] / filename).read_text(encoding="utf-8")
    assert "https://task.staterbill.com,https://bizassist-task.vercel.app" in code


def test_deploy_updates_secrets_and_checks_readiness():
    script = Path(__file__).resolve().parents[1] / "deploy_cloudrun.ps1"
    code = "\n".join(line for line in script.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#"))
    assert "--set-env-vars" not in code
    assert "--set-secrets" not in code
    assert "--update-secrets" in code
    for name in ("DATABASE_URL", "JWT_SECRET", "TASK_CRON_SECRET"):
        assert f"{name}={name}:latest" in code
    assert '[string]$AllowedOrigins = "https://task.staterbill.com,https://bizassist-task.vercel.app"' in code
    assert "$health.pro_required -ne $true" in code
    assert "$health.cloud_only -ne $true" in code
