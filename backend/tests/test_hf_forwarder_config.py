# Observed counterexamples on the unfixed code (task 1.1):
#   ops/hf-forwarder/default.conf does not exist (no forwarder);
#   ops/hf-forwarder/README.md does not exist (no Space header).
"""
tests/test_hf_forwarder_config.py
=================================
Bug condition exploration for C1.5 (bugfix 1.33, design Property 1 and
Property 3): desktop apps installed before this fix call the Hugging Face URL,
so the Space must forward to the Cloud Run billing API.

The forwarder is plain nginx configuration in ops/hf-forwarder/: default.conf
proxies to the Cloud Run URL without buffering (SSE and uploads stream), and
the Space README header declares a Docker Space on port 7860.
"""
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

REPO_ROOT = Path(__file__).resolve().parents[2]
FORWARDER_DIR = REPO_ROOT / "ops" / "hf-forwarder"
CLOUD_RUN_HOST = "staterbill-api-1076771386585.asia-south1.run.app"


def _nginx_directives(text: str) -> list:
    """(name, args) for every directive and block header, comments removed."""
    body = re.sub(r"#[^\n]*", "", text)
    directives = []
    for statement in re.split(r"[;{}]", body):
        parts = statement.split()
        if parts:
            directives.append((parts[0], parts[1:]))
    return directives


def _space_header(text: str) -> dict:
    """The key: value pairs of the YAML front matter that a Space README starts with."""
    m = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", text.lstrip("\ufeff"), re.S)
    if not m:
        return {}
    header = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            key, value = line.split(":", 1)
            header[key.strip()] = value.strip().strip("'\"")
    return header


def test_forwarder_proxies_to_cloud_run_without_buffering():
    """**Validates: Requirements 1.33 (expected 2.33)**"""
    conf = FORWARDER_DIR / "default.conf"
    assert conf.is_file(), f"no forwarder configuration at {conf.relative_to(REPO_ROOT)}"
    directives = _nginx_directives(conf.read_text(encoding="utf-8"))
    targets = [urlparse(args[0]) for name, args in directives if name == "proxy_pass" and args]
    assert any(t.scheme == "https" and t.hostname == CLOUD_RUN_HOST for t in targets), (
        f"proxy_pass does not target https://{CLOUD_RUN_HOST}: {[t.geturl() for t in targets]}"
    )
    assert ("proxy_buffering", ["off"]) in directives, "proxy_buffering is not off"


def test_forwarder_space_header_declares_docker_on_7860():
    """**Validates: Requirements 1.33 (expected 2.33)**"""
    readme = FORWARDER_DIR / "README.md"
    assert readme.is_file(), f"no Space README at {readme.relative_to(REPO_ROOT)}"
    header = _space_header(readme.read_text(encoding="utf-8"))
    assert {k: header.get(k) for k in ("sdk", "app_port")} == {"sdk": "docker", "app_port": "7860"}, (
        f"Space header: {header}"
    )
