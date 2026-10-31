"""Legacy diagnostics must neither embed credentials nor connect on import."""
import ast
import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize("filename", ["check_cloud_db.py", "cloud_db_check.py", "compare_schema.py", "dump_schema.py"])
def test_diagnostic_import_does_not_open_database(filename, monkeypatch):
    import psycopg2
    import sqlite3
    def denied(*_args, **_kwargs):
        pytest.fail("Import attempted a database connection")
    monkeypatch.setattr(psycopg2, "connect", denied)
    monkeypatch.setattr(sqlite3, "connect", denied)
    source = Path(__file__).resolve().parents[1] / filename
    tree = ast.parse(source.read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Constant) and isinstance(node.value, str)
                   and node.value.startswith(("postgresql://", "postgres://")) for node in ast.walk(tree))
    spec = importlib.util.spec_from_file_location("audit_" + source.stem, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.main)
