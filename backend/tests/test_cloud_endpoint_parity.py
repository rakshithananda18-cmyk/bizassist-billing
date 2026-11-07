"""Desktop and Python services must resolve overrides identically."""
import itertools
import json
import shutil
import subprocess
from pathlib import Path
import pytest


def test_endpoint_precedence_matches_desktop_for_all_overrides():
    from core.cloud_endpoint import resolve_cloud_url, DEFAULT_CLOUD_URL
    keys = ("CLOUD_API_URL","VITE_API_URL","CLOUD_URL","BIZASSIST_CLOUD_URL")
    values = (None,"","  ","https://a.example/","not a url","https://x.hf.space")
    cases = [{k:v for k,v in zip(keys, combination) if v is not None} for combination in itertools.product(values,repeat=4)]
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    module = str(Path(__file__).resolve().parents[2] / 'desktop/src/cloudEndpoint.js')
    script = "const c=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(e=>c.resolveCloudApiUrl(e)))));"
    result = subprocess.run([node,'-e',script,module],input=json.dumps(cases),text=True,capture_output=True,timeout=30,check=True)
    assert json.loads(result.stdout) == [resolve_cloud_url(case)[0] for case in cases]
    assert resolve_cloud_url({}) == (DEFAULT_CLOUD_URL,"default")
