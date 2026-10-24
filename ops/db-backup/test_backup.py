"""ops/db-backup/backup.py - the parts that need no database or bucket."""
import datetime

import pytest

import backup


class TestLibpqUrl:

    def test_sqlalchemy_schemes_become_postgresql(self):
        assert backup.libpq_url("postgresql+psycopg2://u:p@db.example.com:5432/postgres") == \
            "postgresql://u:p@db.example.com:5432/postgres"
        assert backup.libpq_url("postgres://u:p@db.example.com/postgres") == \
            "postgresql://u:p@db.example.com/postgres"

    def test_supabase_transaction_pooler_is_switched_to_session_mode(self):
        url = "postgresql://postgres.abc:p@aws-0-ap-south-1.pooler.supabase.com:6543/postgres?pgbouncer=true&sslmode=require"
        assert backup.libpq_url(url) == \
            "postgresql://postgres.abc:p@aws-0-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=require"

    def test_other_hosts_keep_their_port(self):
        assert backup.libpq_url("postgresql://u:p@db.example.com:6543/x") == "postgresql://u:p@db.example.com:6543/x"

    def test_not_postgres_is_refused(self):
        with pytest.raises(ValueError):
            backup.libpq_url("sqlite:///./bizassist.db")


def test_tables_in_reads_pg_restore_listing():
    listing = """
;
; Archive created at 2026-10-24 20:30:01 UTC
3456; 1259 16390 TABLE public invoices postgres
4001; 0 16390 TABLE DATA public invoices postgres
4002; 0 16400 TABLE DATA public ft_tasks postgres
4003; 0 16410 SEQUENCE SET public invoices_id_seq postgres
"""
    assert backup.tables_in(listing) == {"invoices", "ft_tasks"}


def test_object_names_sort_by_date():
    t = datetime.datetime(2026, 10, 24, 20, 30, 1, tzinfo=datetime.timezone.utc)
    assert backup.object_name(t) == "2026/10/24/bizassist-20261024-203001Z.dump"


def test_missing_settings_fail_without_touching_anything(monkeypatch, capsys):
    monkeypatch.delenv("BACKUP_BUCKET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert backup.main() == 2
    assert "required" in capsys.readouterr().out


def test_a_dump_without_the_core_tables_is_not_uploaded(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKUP_BUCKET", "b")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.com/postgres")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd[0])
        if cmd[0] == "pg_dump":
            path = next(a for a in cmd if a.startswith("--file=")).split("=", 1)[1]
            open(path, "wb").write(b"x")
            assert "DATABASE_URL" not in kw["env"], "the URL goes to pg_dump only as its argument"
            return ""
        return "4001; 0 1 TABLE DATA public users postgres\n"

    monkeypatch.setattr(backup, "run", fake_run)
    with pytest.raises(RuntimeError, match="missing"):
        backup.main()
    assert calls == ["pg_dump", "pg_restore"]
