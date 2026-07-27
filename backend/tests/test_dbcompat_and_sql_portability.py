"""
tests/test_dbcompat_and_sql_portability.py
==========================================
The money scripts now point at PRODUCTION Postgres as well as local SQLite, and
there is no PostgreSQL server in CI or in the sandbox they were written in. That
is the same gap that produced finding N4b-PG (§63), where a guard verified on
SQLite alone shipped `ROUND(<double precision>, 2)` — a function Postgres does
not have — and took every subsequent migration step down with it.

So this file proves what CAN be proved without a server, and the docstrings say
plainly what cannot:

  1. **The translation layer**, against a fake connection that reproduces
     psycopg2's paramstyle (`%s`), its `%`-escaping rule, and its abort-on-error
     transaction semantics.
  2. **A SQL portability gate** — a checked-in analyser over the scripts' own
     source, failing on the constructs known to differ between the two engines.
     This is architecture rule 20: where there is no engine to move the rule
     into, the rule goes into a checked-in analyser with a gate.

WHAT THIS DOES NOT PROVE
------------------------
That the queries return correct results on a real PostgreSQL server. Nothing
here executes against one. The AUDIT is read-only and engine-enforced read-only,
so it is the safe thing to run first; treat its first cloud run as the
verification, and only then consider the repair.
"""
import contextlib
import io
import os
import re
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock")

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _BACKEND)
sys.path.insert(0, os.path.join(_BACKEND, "scripts"))

import sqlite3

import pytest

import _dbcompat as DBC
import audit_money_integrity as AUDIT
import repair_line_items_by_invariant as RLI


# ══════════════════════════════════════════════════════════════════════════════
# 1. Placeholder / percent translation
# ══════════════════════════════════════════════════════════════════════════════

def test_sqlite_sql_is_returned_byte_identical():
    """The local path must not change at all. Every integrity figure in the
    review was produced by these exact strings."""
    sql = "SELECT 1 FROM t WHERE a = ? AND b LIKE 'x%' AND c = ?"
    assert DBC.translate(sql, DBC.SQLITE, True) == sql
    assert DBC.translate(sql, DBC.SQLITE, False) == sql


def test_question_marks_become_percent_s_for_postgres():
    out = DBC.translate("SELECT 1 FROM t WHERE a = ? AND b = ?", DBC.POSTGRES, True)
    assert out == "SELECT 1 FROM t WHERE a = %s AND b = %s"


def test_a_question_mark_inside_a_string_literal_is_data_not_a_placeholder():
    """No query in the tree has one today — which is exactly why a naive
    `str.replace` would survive review and corrupt a query written next year."""
    out = DBC.translate("SELECT 1 WHERE note = 'why?' AND id = ?",
                        DBC.POSTGRES, True)
    assert out == "SELECT 1 WHERE note = 'why?' AND id = %s"


def test_percent_is_escaped_only_when_parameters_are_present():
    """psycopg2 interpolates only when it is given parameters. `LIKE 'x%'` is
    fine with none and raises `unsupported format character` with any."""
    sql = "SELECT 1 FROM t WHERE note LIKE 'Initial payment for invoice %'"
    assert DBC.translate(sql, DBC.POSTGRES, False) == sql
    assert DBC.translate(sql, DBC.POSTGRES, True) == (
        "SELECT 1 FROM t WHERE note LIKE 'Initial payment for invoice %%'")


def test_the_real_section_A_query_survives_translation():
    """The audit's section A is the one query that mixes a LIKE wildcard with a
    parameterised follow-up. Pinned because it is the shape that breaks."""
    sql = ("SELECT * FROM invoice_payments "
           "WHERE note LIKE 'Initial payment for invoice %' AND business_id = ?")
    out = DBC.translate(sql, DBC.POSTGRES, True)
    assert "%%'" in out and out.endswith("= %s")


def test_a_doubled_quote_inside_a_literal_does_not_end_the_literal():
    out = DBC.translate("SELECT 1 WHERE s = 'it''s ? here' AND id = ?",
                        DBC.POSTGRES, True)
    assert out == "SELECT 1 WHERE s = 'it''s ? here' AND id = %s"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Rows behave identically on both drivers
# ══════════════════════════════════════════════════════════════════════════════

def test_row_supports_name_and_position_and_dict():
    """The scripts use `r["col"]`, `r[0]` AND `dict(r)`. psycopg2's cursors give
    only one of those; RealDictCursor breaks `r[0]`, NamedTupleCursor mangles
    non-identifier column names. Hence the explicit Row."""
    r = DBC.Row(("a", 2), {"name": 0, "n": 1})
    assert r["name"] == "a" and r[0] == "a"
    assert r["n"] == 2 and r[1] == 2
    assert dict(r) == {"name": "a", "n": 2}
    assert r.keys() == ["name", "n"]
    assert r.get("missing", "dflt") == "dflt"


def test_row_names_the_columns_it_does_have_when_asked_for_one_it_does_not():
    r = DBC.Row((1,), {"id": 0})
    with pytest.raises(KeyError) as e:
        r["nope"]
    assert "id" in str(e.value)


# ══════════════════════════════════════════════════════════════════════════════
# 3. A fake psycopg2 with real Postgres semantics
# ══════════════════════════════════════════════════════════════════════════════

class _PgCursor:
    """Reproduces the two psycopg2 behaviours that matter here: `%s` paramstyle
    (a `?` is a syntax error) and transaction abort on failure."""

    def __init__(self, conn):
        self._c = conn
        self.description = None
        self.rowcount = -1

    def execute(self, sql, params=None):
        if self._c.aborted:
            raise RuntimeError("current transaction is aborted, commands "
                               "ignored until end of transaction block")
        if "?" in _strip_literals(sql):
            self._c.aborted = True
            raise RuntimeError(f'syntax error at or near "?" -- {sql}')
        # THE INTERPOLATION RULE, and the reason this fake was not faithful
        # enough the first time. psycopg2 skips the format pass ONLY when
        # `vars is None`. Given an empty tuple it still interpolates, so a
        # literal `%` in the SQL raises `IndexError: tuple index out of range`.
        # The original fake tested `if params:`, which is False for `()` — so it
        # waved through exactly the call that failed on the first cloud run.
        if params is not None:
            n_slots = len(re.findall(r"%[^%]", _strip_literals(sql)))
            if n_slots != len(params):
                raise IndexError("tuple index out of range")
        self._c.seen.append(sql)
        self.description = [("id",), ("v",)]
        self.rowcount = 0
        self._rows = []
        return None

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)

    def close(self):
        pass


def _strip_literals(sql):
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


class _PgConn:
    def __init__(self):
        self.seen = []
        self.aborted = False
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _PgCursor(self)

    def commit(self):
        if self.aborted:
            raise RuntimeError("cannot commit an aborted transaction")
        self.commits += 1

    def rollback(self):
        self.aborted = False
        self.rollbacks += 1

    def close(self):
        pass


def _pg():
    raw = _PgConn()
    return DBC.Conn(raw, DBC.POSTGRES, "postgresql://u:***@h/db", False), raw


def test_a_parameterised_query_reaches_postgres_with_percent_s():
    conn, raw = _pg()
    conn.execute("SELECT id FROM t WHERE business_id = ? AND user_id = ?", (1, 2))
    assert raw.seen[-1].endswith("business_id = %s AND user_id = %s")


def test_a_query_with_a_LIKE_wildcard_and_NO_params_does_not_interpolate():
    """THE FIRST REAL CLOUD FAILURE, pinned.

    Audit section A is `... note LIKE 'Initial payment for invoice %'` with no
    parameters. The layer passed `()` rather than `None`, psycopg2 ran its format
    pass anyway, and the `%'` became a format specifier:
    `IndexError: tuple index out of range`.

    sqlite3 does not care whether it gets `()` or `None`, so this was invisible
    locally — the same one-dialect blindness as N4b-PG, one layer down.
    """
    conn, raw = _pg()
    conn.execute("SELECT * FROM invoice_payments "
                 "WHERE note LIKE 'Initial payment for invoice %'")
    assert raw.seen[-1].endswith("%'"), (
        "with no parameters the % must be left alone, not doubled")


def test_a_LIKE_wildcard_WITH_params_is_escaped():
    conn, raw = _pg()
    conn.execute("SELECT * FROM invoice_payments "
                 "WHERE note LIKE 'Initial payment %' AND business_id = ?", (7,))
    sql = raw.seen[-1]
    assert "%%'" in sql and sql.endswith("= %s")


def test_the_empty_tuple_is_never_handed_to_the_driver():
    """The fix is `params if params else None`. Asserted on behaviour: the fake
    raises IndexError for any non-None vars whose slot count disagrees."""
    conn, _ = _pg()
    conn.execute("SELECT 1 FROM t WHERE note LIKE 'x %'", ())   # must not raise


def test_an_untranslated_question_mark_would_be_a_syntax_error():
    """Proves the fake is strict enough to be worth trusting: without the
    translation layer, these queries fail."""
    conn, raw = _pg()
    with pytest.raises(RuntimeError, match="syntax error"):
        raw.cursor().execute("SELECT 1 WHERE a = ?", (1,))


def test_table_exists_uses_information_schema_on_postgres():
    conn, raw = _pg()
    conn.table_exists("invoices")
    sql = raw.seen[-1]
    assert "information_schema.tables" in sql and "sqlite_master" not in sql
    assert "= %s" in sql


def test_table_exists_uses_sqlite_master_on_sqlite(tmp_path):
    p = tmp_path / "test_te.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE invoices (id INTEGER PRIMARY KEY)")
    con.commit()
    c = DBC.Conn(con, DBC.SQLITE, str(p), False)
    assert c.table_exists("invoices") is True
    assert c.table_exists("nope") is False


def test_integrity_report_does_not_run_pragmas_on_postgres():
    """A PRAGMA on Postgres is a syntax error that would abort the transaction —
    the §63 cascade shape."""
    conn, raw = _pg()
    rep = conn.integrity_report()
    assert not any("PRAGMA" in s.upper() for s in raw.seen)
    assert rep["fk_violations"] == 0
    assert "engine" in rep["note"]
    assert not raw.aborted


def test_integrity_report_never_reports_absent_as_clean():
    """Rule 33 / rule 63. `fk_violations` must be an int only when it was
    actually measured; the note must say how."""
    conn, _ = _pg()
    rep = conn.integrity_report()
    assert rep["integrity"] == "n/a (engine-enforced)"
    assert rep["note"], "a figure with no stated method is not a measurement"


# ── Connection failures must be answers, not tracebacks ──────────────────────
# The first real run of this tool ended in a nine-frame psycopg2 traceback saying
# `could not translate host name "HOST"`. The actual problem was that the runbook's
# example DSN had been pasted unedited. An operator holding a production database
# deserves to be told which of the three things went wrong.

@pytest.mark.parametrize("url", [
    "postgresql://USER:PASS@HOST:5432/DBNAME",
    "postgresql://user:pass@host:5432/DBNAME",
    "postgresql://postgres.<project-ref>:<password>@x.pooler.supabase.com:5432/postgres",
    "<SUPABASE_DATABASE_URL_FROM_SECRET>",
])
def test_an_unedited_placeholder_dsn_is_named_as_such(url):
    assert DBC._looks_like_a_placeholder(url), url


@pytest.mark.parametrize("url", [
    "postgresql://postgres.abcdefg:s3cret@eu-west-2.pooler.supabase.com:5432/postgres",
    "postgresql://bizassist:hunter2@10.0.0.4:6543/postgres",
])
def test_a_real_looking_dsn_is_not_mistaken_for_a_placeholder(url):
    """The check must not block a legitimate connection — a false positive here
    stops the audit running at all."""
    assert not DBC._looks_like_a_placeholder(url), url


def test_the_placeholder_message_does_not_echo_the_password(capsys):
    with pytest.raises(SystemExit) as e:
        DBC.connect("postgresql://USER:hunter2@HOST:5432/DBNAME", readonly=True)
    assert "hunter2" not in str(e.value)
    assert "placeholder" in str(e.value).lower()


def test_a_connection_failure_says_what_to_do_and_hides_the_password():
    """Exercised against an address that cannot accept a connection."""
    pytest.importorskip("psycopg2")
    with pytest.raises(SystemExit) as e:
        DBC.connect("postgresql://bizassist:hunter2@127.0.0.1:1/postgres",
                    readonly=True)
    msg = str(e.value)
    assert "hunter2" not in msg, "the DSN password reached the error output"
    assert "Could not connect" in msg
    assert "Nothing was read and nothing was changed" in msg
    assert "Traceback" not in msg


def test_tls_is_forced_for_a_remote_database():
    """psycopg2 defaults to `sslmode=prefer`, which silently falls back to
    PLAINTEXT if the server does not offer TLS. This tool carries a production
    credential to a pooler across the public internet; a silent downgrade is not
    an acceptable default."""
    out = DBC._with_sslmode(
        "postgresql://u:p@aws-1-ap-south-1.pooler.supabase.com:5432/postgres")
    assert out.endswith("?sslmode=require")


def test_an_explicit_sslmode_is_respected():
    url = "postgresql://u:p@remote.example.com:5432/db?sslmode=verify-full"
    assert DBC._with_sslmode(url) == url


def test_sslmode_is_appended_with_an_ampersand_when_options_exist():
    out = DBC._with_sslmode("postgresql://u:p@remote:5432/db?connect_timeout=5")
    assert out.endswith("&sslmode=require") and "?connect_timeout=5" in out


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_tls_is_not_forced_for_a_local_socket(host):
    """A developer Postgres on localhost usually has no certificate, and it is
    the one setup where the credential never leaves the machine."""
    url = f"postgresql://u:p@{host}:5432/db"
    assert DBC._with_sslmode(url) == url


def test_readonly_enforcement_fails_CLOSED_when_the_server_refuses():
    """Rules 17-18. If the read-only guarantee cannot be established, stop —
    do not carry on printing `mode: read-only` over a writable session.

    This is the PgBouncer transaction-pooler case: port 6543 rejects
    session-level SET, and without this the banner would lie.
    """
    class RefusingConn:
        def __init__(self):
            self.closed = False

        def cursor(self):
            raise RuntimeError('SET is not allowed in transaction pooling mode')

        def close(self):
            self.closed = True

    raw = RefusingConn()
    with pytest.raises(SystemExit) as e:
        DBC._enforce_readonly(raw, "postgresql://u:p@h:6543/db")
    msg = str(e.value)
    assert "Refusing to continue" in msg
    assert "6543" in msg and "5432" in msg
    assert raw.closed, "the connection must be closed on the fail-closed path"


def test_readonly_enforcement_rejects_a_server_that_says_off():
    """`SET` succeeding is not proof; the value is read back."""
    class LyingConn:
        def __init__(self):
            self.closed = False

        def cursor(self):
            outer = self

            class C:
                def execute(self, sql):
                    pass

                def fetchone(self):
                    return ("off",)

                def close(self):
                    pass
            return C()

        def commit(self):
            pass

        def close(self):
            self.closed = True

    raw = LyingConn()
    with pytest.raises(SystemExit) as e:
        DBC._enforce_readonly(raw, "postgresql://u:p@h/db")
    assert "did not accept read-only" in str(e.value)
    assert raw.closed


def test_readonly_enforcement_passes_when_the_server_confirms_on():
    class GoodConn:
        def cursor(self):
            class C:
                def execute(self, sql):
                    pass

                def fetchone(self):
                    return ("on",)

                def close(self):
                    pass
            return C()

        def commit(self):
            pass

        def close(self):
            raise AssertionError("must not close a healthy connection")

    DBC._enforce_readonly(GoodConn(), "postgresql://u:p@h/db")   # must not raise


def test_a_pooler_hangup_is_explained_rather_than_dumped():
    """`server closed the connection unexpectedly` is almost never a bad
    password — it is a paused Supabase project. Say so."""
    src = open(os.path.join(_BACKEND, "scripts", "_dbcompat.py"),
               encoding="utf-8").read()
    assert "server closed the connection unexpectedly" in src
    assert "PAUSED" in src


# ── A money audit must not die of a console code page ────────────────────────
# The first successful cloud run reached section B, reported 63 documents with no
# journal entry, and then raised
#     UnicodeEncodeError: 'charmap' codec can't encode character '₹'
# because a Windows console is cp1252 and the amounts print with ₹. Sections C
# through J were never rendered. The findings existed; the operator could not see
# them — and an unreadable answer and no answer are the same answer.

class _Cp1252Stdout(io.TextIOBase):
    """A console that cannot encode ₹ and cannot be reconfigured."""
    encoding = "cp1252"

    def __init__(self):
        self.buf = []

    def write(self, s):
        s.encode("cp1252")          # raises exactly like the real console
        self.buf.append(s)
        return len(s)


class _Utf8Stdout(io.TextIOBase):
    encoding = "utf-8"

    def __init__(self):
        self.buf = []

    def write(self, s):
        self.buf.append(s)
        return len(s)


@contextlib.contextmanager
def _as_console(stream):
    """Swap sys.stdout INSIDE the test body, not in a fixture.

    pytest re-installs its own capture object on `sys.stdout` between the
    setup and call phases, so a fixture that swaps the stream has it silently
    replaced before the test runs — the assertions then read an empty buffer
    while the output goes to pytest's capture. Cost an hour; recorded so the
    next person does not repeat it.
    """
    real, DBC._ASCII_ONLY = sys.stdout, None
    sys.stdout = stream
    try:
        yield stream
    finally:
        sys.stdout = real
        DBC._ASCII_ONLY = None


def test_a_rupee_amount_survives_a_cp1252_console():
    with _as_console(_Cp1252Stdout()) as s:
        DBC.out("biz 6 INV-1 ₹3,298.30")
    written = "".join(s.buf)
    assert "Rs 3,298.30" in written
    assert all(ord(c) < 128 for c in written)


def test_dashes_and_arrows_are_transliterated_too():
    with _as_console(_Cp1252Stdout()) as s:
        DBC.out("header — lines → total … ok")
    assert "".join(s.buf).strip() == "header - lines -> total ... ok"


def test_use_utf8_stdout_never_raises_on_a_stream_it_cannot_reconfigure():
    with _as_console(_Cp1252Stdout()) as s:
        DBC.use_utf8_stdout()       # no .reconfigure on this stream
        DBC.out("₹1")               # and the report still runs
    assert "Rs 1" in "".join(s.buf)


def test_a_utf8_console_keeps_the_real_glyphs():
    """The transliteration is a fallback, not a downgrade for everyone. A UTF-8
    terminal — and any redirect to a file — must still get ₹."""
    with _as_console(_Utf8Stdout()) as s:
        DBC.out("₹3,298.30 — ok")
    assert "₹3,298.30 — ok" in "".join(s.buf)


def test_an_unforeseen_character_degrades_rather_than_terminating():
    """Belt and braces: anything not in the transliteration table must still not
    kill the run."""
    with _as_console(_Cp1252Stdout()) as s:
        DBC.out("emoji \U0001F600 and CJK 中")
    assert s.buf, "nothing was written at all"


def test_a_sqlite_path_with_spaces_and_parens_opens_read_only(tmp_path):
    """The owner's checkout lives under `D:\\Dev Workspace\\ai_agent_lab_google(1)`
    — a space, parentheses and backslashes, none valid unescaped in a URI."""
    d = tmp_path / "Dev Workspace" / "ai_agent_lab_google(1)"
    d.mkdir(parents=True)
    p = d / "test_spaces.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE invoices (id INTEGER PRIMARY KEY)")
    con.execute("INSERT INTO invoices VALUES (1)")
    con.commit()
    con.close()

    uri = DBC._readonly_uri(str(p))
    assert " " not in uri and "(" not in uri, f"unescaped URI: {uri}"
    assert uri.startswith("file:") and uri.endswith("?mode=ro")

    c = DBC.connect(str(p), readonly=True)
    assert c.scalar("SELECT COUNT(*) FROM invoices") == 1
    c.close()


def test_a_readonly_sqlite_connection_cannot_write(tmp_path):
    """`mode=ro` is the enforcement, not a convention — the audit is now pointed
    at real databases."""
    p = tmp_path / "test_ro.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()
    c = DBC.connect(str(p), readonly=True)
    with pytest.raises(Exception):
        c.execute("INSERT INTO t VALUES (1)")
    c.close()


def test_a_missing_database_names_the_ABSOLUTE_path_it_looked_for(tmp_path):
    """`unable to open database file` on a relative path tells the operator
    nothing about WHERE it looked — which is exactly how a wrong default
    directory goes undiagnosed."""
    with pytest.raises(SystemExit) as e:
        DBC.connect(str(tmp_path / "nope.db"), readonly=True)
    msg = str(e.value)
    assert str(tmp_path) in msg, "the path it tried must be in the message"
    assert "Refusing to guess" in msg


def test_the_backlog_script_resolves_to_backend_not_to_scripts():
    """Rule 45, with the correction: resolve from `__file__` AND to the right
    directory. The first version pointed at `backend/scripts/bizassist.db`."""
    sys.path.insert(0, os.path.join(_BACKEND, "scripts"))
    import check_local_sync_backlog as CLS
    default = CLS._default_db()
    assert os.path.basename(default) == "bizassist.db"
    assert os.path.basename(os.path.dirname(default)) == "backend", default
    assert "scripts" not in os.path.dirname(default)


def test_a_postgres_dsn_password_is_redacted():
    assert DBC._redact("postgresql://user:hunter2@host:5432/db") == \
        "postgresql://user:***@host:5432/db"
    assert "hunter2" not in DBC._redact("postgres://user:hunter2@h/db")


def test_postgres_urls_are_recognised_and_paths_are_not():
    assert DBC.is_postgres_target("postgresql://h/db")
    assert DBC.is_postgres_target("postgres://h/db")
    assert not DBC.is_postgres_target("/backend/bizassist.db")
    assert not DBC.is_postgres_target("bizassist.db")


def test_the_audit_never_inherits_DATABASE_URL_by_accident(monkeypatch):
    """A money script that silently follows whatever the app is pointed at is one
    stray shell export away from running against production while you believe
    you are on a copy. Only the dedicated variable is honoured."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://prod/db")
    monkeypatch.delenv("BIZASSIST_AUDIT_DATABASE_URL", raising=False)
    assert not DBC.is_postgres_target(DBC.resolve_target(None))
    monkeypatch.setenv("BIZASSIST_AUDIT_DATABASE_URL", "postgresql://replica/db")
    assert DBC.resolve_target(None) == "postgresql://replica/db"
    assert DBC.resolve_target("/explicit.db") == "/explicit.db"


# ══════════════════════════════════════════════════════════════════════════════
# 4. THE GATE — SQL portability analyser over the scripts' own source
# ══════════════════════════════════════════════════════════════════════════════

_SCRIPTS = [
    os.path.join(_BACKEND, "scripts", "audit_money_integrity.py"),
    os.path.join(_BACKEND, "scripts", "repair_line_items_by_invariant.py"),
    os.path.join(_BACKEND, "scripts", "diagnose_money_findings.py"),
    os.path.join(_BACKEND, "scripts", "reconcile_local_vs_cloud.py"),
]

# Each entry: (name, regex, why it breaks). Checked against source with comments
# and docstrings removed, so the files can still EXPLAIN the hazard in prose —
# several of them do at length, and those explanations are the point.
#
# CASE MATTERS for the ROUND rule, and getting it wrong was the gate's first
# bug: a case-insensitive `\bround\s*\(.*,\s*\d\)` flags PYTHON's `round(v, 2)`,
# which is precisely the fix. SQL in this codebase is uppercase by convention, so
# the rule matches uppercase ROUND anywhere, and lowercase `round(` only on lines
# that are visibly SQL. A gate that fires on the correct code is a gate people
# switch off.
_BANNED = [
    ("two-argument ROUND",
     r"\bROUND\s*\([^;]*,\s*\d+\s*\)",
     "Postgres has no round(double precision, integer); every money column here "
     "is Column(Float). This is finding N4b-PG exactly."),
    ("PRAGMA outside a dialect branch",
     r"\bPRAGMA\b",
     "SQLite-only. On Postgres it is a syntax error, which aborts the whole "
     "transaction and takes every later statement with it (rule 58)."),
    ("sqlite_master",
     r"\bsqlite_master\b",
     "SQLite-only catalogue; use Conn.table_exists()."),
    ("direct sqlite3 connect",
     r"sqlite3\.connect",
     "bypasses _dbcompat, so the script silently becomes SQLite-only again — "
     "which is how both of these came to be local-only in the first place."),
    ("IFNULL",
     r"\bIFNULL\s*\(",
     "SQLite spelling; COALESCE is standard and works on both."),
    ("strftime in SQL",
     r"\bstrftime\s*\(",
     "SQLite date function; Postgres uses to_char/date_trunc."),
    ("GROUP_CONCAT",
     r"\bGROUP_CONCAT\s*\(",
     "SQLite spelling; Postgres uses string_agg."),
    ("AUTOINCREMENT",
     r"\bAUTOINCREMENT\b",
     "SQLite-only."),
]


def _in_sql(line):
    return bool(re.search(r"\b(SELECT|FROM|WHERE|GROUP BY|HAVING|DELETE|INSERT|"
                          r"UPDATE|JOIN|ORDER BY)\b", line))


def _prose_lines(path):
    """Line numbers holding prose — DOCSTRINGS and comments, and nothing else.

    THE FIRST VERSION OF THIS WAS BROKEN, in the direction that matters.
    It exempted any string literal that did not *look* like SQL, reasoning that
    such a string must be prose. But `c.execute("PRAGMA foreign_key_check")`
    contains no SELECT or FROM, so the PRAGMA rule was skipping the one line in
    the tree it was written to police. A gate with a false negative is worse
    than no gate: it is a green tick over an unchecked file.

    Docstrings are now identified by the AST — a string that is the first
    statement of a module, class or function — so a string handed to `execute()`
    is never mistaken for commentary, whatever it contains.
    """
    import ast
    import io
    import tokenize

    src = open(path, encoding="utf-8").read()
    prose = set()

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            doc = body[0].value
            for ln in range(doc.lineno, (doc.end_lineno or doc.lineno) + 1):
                prose.add(ln)

    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            prose.add(tok.start[0])
    return prose


def _executed_sql(path):
    """-> [(lineno, sql, dialect_guarded)] for every literal passed to execute().

    The precise version of the gate. Regex over lines cannot tell
    `c.execute("PRAGMA ...")` inside `if c.dialect == "sqlite":` — which is
    correct and necessary — from the same call at top level, which would abort a
    Postgres transaction and take every later statement with it (rule 58). The
    AST can, by asking whether any enclosing `if` tests a dialect.
    """
    import ast
    tree = ast.parse(open(path, encoding="utf-8").read())

    def literal(node):
        """The constant parts of a str or f-string; None if neither."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return "".join(v.value for v in node.values
                           if isinstance(v, ast.Constant)
                           and isinstance(v.value, str))
        return None

    found = []

    def walk(node, guarded):
        if isinstance(node, ast.If):
            test = ast.dump(node.test)
            here = guarded or ("dialect" in test or "SQLITE" in test
                               or "sqlite" in test)
            for child in node.body:
                walk(child, here)
            for child in node.orelse:
                walk(child, guarded or "dialect" in test)
            return
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("execute", "executescript")
                and node.args):
            sql = literal(node.args[0])
            if sql:
                found.append((node.lineno, sql, guarded))
        for child in ast.iter_child_nodes(node):
            walk(child, guarded)

    walk(tree, False)
    return found


def _scan(path, pattern):
    """Executable-source hits for `pattern`, skipping prose. Case-SENSITIVE."""
    prose = _prose_lines(path)
    hits = []
    for n, line in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
        if n in prose:
            continue
        code = line.split("#", 1)[0] if not _in_sql(line) else line
        if re.search(pattern, code):
            hits.append(f"{os.path.basename(path)}:{n}: {line.strip()}")
    return hits


@pytest.mark.parametrize("path", _SCRIPTS, ids=lambda p: os.path.basename(p))
def test_no_script_opens_sqlite_directly(path):
    """A PYTHON-level rule, not a SQL one — hence line-based rather than AST.

    `sqlite3.connect` bypasses the compat layer entirely, which is how both of
    these scripts came to be SQLite-only in the first place. Everything about
    the actual SQL is checked by the AST gate below instead: the line-based
    version could not tell a dialect-guarded `PRAGMA` from an unguarded one, nor
    Python's `datetime.strftime` from SQLite's `strftime()`, and a gate that
    fires on correct code is a gate people switch off.
    """
    hits = _scan(path, r"sqlite3\.connect")
    assert not hits, "\n".join(hits)


@pytest.mark.parametrize("path", _SCRIPTS, ids=lambda p: os.path.basename(p))
def test_executed_sql_is_portable_or_explicitly_dialect_guarded(path):
    """The precise gate: every SQL string actually handed to execute().

    This is the check that caught the first gate's false negative — the
    line-based version was exempting `execute("PRAGMA foreign_key_check")` as
    prose because the string contains no SELECT.
    """
    problems = []
    for lineno, sql, guarded in _executed_sql(path):
        if guarded:
            continue                      # inside an `if ... dialect ...` branch
        for name, pattern, why in _BANNED:
            if name == "direct sqlite3 connect":
                continue                  # not a SQL-string rule
            if re.search(pattern, sql, 0 if "ROUND" in name else re.I):
                problems.append(
                    f"{os.path.basename(path)}:{lineno}: {name} in unguarded "
                    f"SQL — {why}\n      {sql.strip()[:120]}")
    assert not problems, "\n".join(problems)


def test_the_precise_gate_can_tell_a_guarded_pragma_from_an_unguarded_one(tmp_path):
    """A gate that cannot fail is decoration — and this one already had a false
    negative, so it gets proven both ways."""
    good = tmp_path / "good.py"
    good.write_text(
        "def f(c):\n"
        "    if c.dialect == 'sqlite':\n"
        "        c.execute('PRAGMA foreign_key_check')\n")
    bad = tmp_path / "bad.py"
    bad.write_text(
        "def f(c):\n"
        "    c.execute('PRAGMA foreign_key_check')\n")

    assert _executed_sql(str(good)) == [(3, "PRAGMA foreign_key_check", True)]
    assert _executed_sql(str(bad)) == [(2, "PRAGMA foreign_key_check", False)]


def test_the_precise_gate_sees_into_f_strings(tmp_path):
    """Nearly every query in these scripts is an f-string with an interpolated
    table name. A gate that only understood plain constants would be blind to
    all of them."""
    p = tmp_path / "fs.py"
    p.write_text(
        "def f(c, t):\n"
        "    c.execute(f'SELECT ROUND(SUM(x), 2) FROM {t}')\n")
    found = _executed_sql(str(p))
    assert len(found) == 1
    assert "ROUND(SUM(x), 2)" in found[0][1]


@pytest.mark.parametrize("path", _SCRIPTS, ids=lambda p: os.path.basename(p))
def test_no_lowercase_two_arg_round_on_a_sql_line(path):
    """The uppercase rule cannot see `round(x, 2)` written inside SQL in lower
    case. On a line that is visibly SQL, treat it as SQL."""
    hits = []
    for n, line in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
        if _in_sql(line) and re.search(r"\bround\s*\([^;]*,\s*\d+\s*\)", line):
            hits.append(f"{os.path.basename(path)}:{n}: {line.strip()}")
    assert not hits, "lowercase 2-arg ROUND on a SQL line:\n" + "\n".join(hits)


def test_the_gate_would_actually_catch_the_bug_it_was_written_for():
    """A gate that cannot fail is decoration. This is the exact expression that
    broke the cloud on 2026-07-26."""
    pattern = dict((b[0], b[1]) for b in _BANNED)["two-argument ROUND"]
    assert re.search(pattern, "SELECT ROUND(SUM(c.line_total) - (x), 2) FROM t")
    assert not re.search(pattern, "SELECT SUM(c.line_total) - (x) FROM t")


def test_the_gate_does_NOT_flag_pythons_own_round():
    """Its first bug. `round(v, 2)` in Python is the FIX, not the defect, and a
    gate that fires on the correct code is a gate people switch off."""
    pattern = dict((b[0], b[1]) for b in _BANNED)["two-argument ROUND"]
    assert not re.search(pattern, "    return round(float(v or 0.0), 2)")
    assert not re.search(pattern, "        d = round(after[k] - before[k], 2)")


def test_both_scripts_go_through_the_compat_layer():
    for path in _SCRIPTS:
        src = open(path, encoding="utf-8").read()
        assert "from _dbcompat import" in src, (
            f"{os.path.basename(path)} does not use the portable layer")


def test_the_audit_opens_read_only():
    """It is now pointed at production. 'It only runs SELECTs' being true today
    is not the same as it being unable to write."""
    src = open(_SCRIPTS[0], encoding="utf-8").read()
    assert "connect(target, readonly=True)" in src


def test_the_repair_refuses_apply_on_postgres_without_a_backup_acknowledgement(
        monkeypatch, capsys):
    """EXECUTED, not grepped. The refusal must also fire BEFORE the connection
    is attempted — ordered the other way round the operator's first response is
    'psycopg2 is not installed', they install it, re-run the same command, and
    the rail was the only thing standing between them and a live delete."""
    monkeypatch.setattr(sys, "argv",
                        ["repair", "--db", "postgresql://u:pw@h/db", "--apply"])
    with pytest.raises(SystemExit) as e:
        RLI.main()
    msg = str(e.value)
    assert "REFUSING to --apply" in msg
    assert "restorable snapshot" in msg
    assert "psycopg2" not in msg, (
        "the rail fired after the connect() attempt, so it depends on a driver "
        "being absent — which is not a safety property")


def test_the_backup_acknowledgement_lets_it_past_the_rail(monkeypatch):
    """The rail must be the ONLY thing it blocks on; with the flag it proceeds
    to the connection (which then fails here for want of a server). A guard that
    cannot be satisfied is indistinguishable from a broken script."""
    monkeypatch.setattr(sys, "argv",
                        ["repair", "--db", "postgresql://u:pw@h/db", "--apply",
                         "--i-have-a-restorable-backup"])
    with pytest.raises(SystemExit) as e:
        RLI.main()
    assert "REFUSING to --apply" not in str(e.value)


def test_a_sqlite_apply_does_not_need_the_backup_flag(tmp_path, monkeypatch, capsys):
    """The rail is about databases with no .bak beside them. A local file has
    one, and requiring the flag there would train operators to always pass it."""
    path = _repairable_db(tmp_path, "test_rep_norail.db")
    monkeypatch.setattr(sys, "argv",
                        ["repair", "--db", path, "--apply",
                         "--export", str(tmp_path / "e.json")])
    assert RLI.main() == 0
    capsys.readouterr()


def test_the_repair_verifies_before_it_commits():
    """The old shape committed and then re-checked, which is no shape at all for
    a database with no .bak beside it."""
    src = open(_SCRIPTS[1], encoding="utf-8").read()
    verify = src.index("still, still_unres = find_offenders(con, args.business)")
    commit = src.index("con.commit()", verify)
    rollback = src.index("con.rollback()", verify)
    assert rollback < commit, "the rollback path must precede the commit"


def test_the_export_never_contains_a_raw_dsn():
    """The export is written to disk and routinely pasted into tickets; a
    Postgres DSN carries the password."""
    src = open(_SCRIPTS[1], encoding="utf-8").read()
    block = src[src.index("json.dump("):src.index("json.dump(") + 400]
    assert '"database": con.label' in block
    assert "args.db" not in block


# ══════════════════════════════════════════════════════════════════════════════
# 5. The audit still works on SQLite — the port must not have cost anything
# ══════════════════════════════════════════════════════════════════════════════

def _mini(tmp_path, name="test_audit_port.db"):
    p = tmp_path / name
    con = sqlite3.connect(p)
    con.executescript("""
        CREATE TABLE invoices (id INTEGER PRIMARY KEY, business_id INT,
            invoice_id TEXT, invoice_type TEXT, total_amount REAL, amount REAL,
            cash_discount REAL, round_off REAL, paid_amount REAL, status TEXT);
        CREATE TABLE invoice_line_items (id INTEGER PRIMARY KEY, invoice_id INT,
            line_total REAL);
        CREATE TABLE invoice_payments (id INTEGER PRIMARY KEY, business_id INT,
            invoice_id INT, amount_paid REAL, note TEXT);
        INSERT INTO invoices VALUES (1,1,'INV-1',NULL,200.0,200.0,0,0,0,'Pending');
        INSERT INTO invoice_line_items VALUES (1,1,200.0);
    """)
    con.commit()
    return DBC.connect(str(p), readonly=False)


def test_audit_reports_clean_on_a_consistent_database(tmp_path):
    rep = AUDIT.audit(_mini(tmp_path))
    assert rep.failures == 0


def test_audit_check_I_still_fires_after_the_ROUND_removal(tmp_path):
    """The port rewrote every check that used SQL ROUND. A clean run proves
    nothing; this proves the rewritten SQL can still SEE corruption."""
    c = _mini(tmp_path, "test_audit_dirty.db")
    c.execute("UPDATE invoice_line_items SET line_total = 450.0 WHERE id = 1")
    c.commit()
    rep = AUDIT.audit(c)
    titles = [t for t, rows, _ in rep.sections if rows]
    assert any(t.startswith("I.") for t in titles), (
        f"check I went blind after the ROUND removal; firing checks: {titles}")


def test_audit_tolerance_still_absorbs_paise_but_not_a_whole_line(tmp_path):
    c = _mini(tmp_path, "test_audit_tol.db")
    c.execute("UPDATE invoice_line_items SET line_total = 200.40 WHERE id = 1")
    c.commit()
    assert AUDIT.audit(c).failures == 0, "40 paise must not be an alarm"
    c.execute("UPDATE invoice_line_items SET line_total = 201.50 WHERE id = 1")
    c.commit()
    assert AUDIT.audit(c).failures > 0, "1.50 is over tolerance and must fire"


def test_r_rounds_none_to_zero_without_raising():
    assert AUDIT._r(None) == 0.0
    assert AUDIT._r(3.14159) == 3.14
    assert AUDIT._r(2) == 2.0


# ══════════════════════════════════════════════════════════════════════════════
# 6. The production rail — verify BEFORE commit
# ══════════════════════════════════════════════════════════════════════════════
# The repair used to delete, COMMIT, and only then re-check the invariant and
# print the money diff. If the re-check came back dirty the rows were already
# gone. Survivable next to a local .bak; not the right shape for a cloud
# database serving live businesses. These tests are the rail, executed.

def _repairable_db(tmp_path, name):
    """An invoice whose first line reconciles to the header and whose second is
    a phantom — the M-16/M-17/M-18 shape, on the smallest schema that works."""
    p = tmp_path / name
    con = sqlite3.connect(p)
    con.executescript("""
        CREATE TABLE invoices (id INTEGER PRIMARY KEY, business_id INT,
            invoice_id TEXT, total_amount REAL, cash_discount REAL,
            round_off REAL, paid_amount REAL);
        CREATE TABLE invoice_line_items (id INTEGER PRIMARY KEY, invoice_id INT,
            product_name TEXT, quantity REAL, unit_price REAL, line_total REAL,
            created_at TEXT);
        CREATE TABLE invoice_payments (id INTEGER PRIMARY KEY, business_id INT,
            invoice_id INT, amount_paid REAL, note TEXT);
        CREATE TABLE journal_lines (id INTEGER PRIMARY KEY, debit REAL, credit REAL);
        CREATE TABLE stock_ledger (id INTEGER PRIMARY KEY);
        INSERT INTO invoices VALUES (1,1,'INV-1',100.0,0,0,0);
        INSERT INTO invoice_line_items VALUES (1,1,'A',1,100.0,100.0,'2026-07-01');
        INSERT INTO invoice_line_items VALUES (2,1,'A',1,40.0,40.0,'2026-07-20');
    """)
    con.commit()
    con.close()
    return str(p)


def test_the_repair_finds_the_phantom_row(tmp_path):
    c = DBC.connect(_repairable_db(tmp_path, "test_rep_find.db"), readonly=False)
    repairable, unresolved = RLI.find_offenders(c)
    assert len(repairable) == 1 and not unresolved
    assert [l["id"] for l in repairable[0]["delete"]] == [2]
    assert repairable[0]["delete_value"] == 40.0


def test_an_unexpected_money_move_rolls_the_whole_repair_back(tmp_path, monkeypatch,
                                                              capsys):
    """THE RAIL. If any figure the repair is not allowed to touch moves, nothing
    is committed — rather than the old behaviour of reporting `<== UNEXPECTED`
    after the rows were already gone.

    Simulated by making the AFTER snapshot disagree on `payments_sum`, which is
    what a repair with a bad WHERE clause would actually look like.
    """
    path = _repairable_db(tmp_path, "test_rep_rollback.db")
    real = RLI.money_snapshot
    calls = {"n": 0}

    def lying_snapshot(con):
        calls["n"] += 1
        snap = real(con)
        if calls["n"] > 1:                    # the post-delete snapshot
            snap["payments_sum"] = snap["payments_sum"] + 5.0
        return snap

    monkeypatch.setattr(RLI, "money_snapshot", lying_snapshot)
    monkeypatch.setattr(sys, "argv",
                        ["repair", "--db", path, "--apply",
                         "--export", str(tmp_path / "exp.json")])
    rc = RLI.main()
    out = capsys.readouterr().out

    assert rc == 1
    assert "ROLLED BACK" in out and "payments_sum moved" in out
    con = sqlite3.connect(path)
    assert con.execute("SELECT COUNT(*) FROM invoice_line_items").fetchone()[0] == 2, (
        "the phantom row was deleted despite the verification failing")


def test_a_clean_repair_still_commits(tmp_path, monkeypatch, capsys):
    """The rail must not block the good path — a guard that blocks everything is
    indistinguishable from a broken script."""
    path = _repairable_db(tmp_path, "test_rep_commit.db")
    monkeypatch.setattr(sys, "argv",
                        ["repair", "--db", path, "--apply",
                         "--export", str(tmp_path / "exp2.json")])
    rc = RLI.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "deleted 1 row(s)" in out
    assert "invariant re-checked BEFORE commit: 0 repairable" in out
    con = sqlite3.connect(path)
    assert con.execute("SELECT COUNT(*) FROM invoice_line_items").fetchone()[0] == 1
    assert con.execute("SELECT id FROM invoice_line_items").fetchone()[0] == 1, (
        "the wrong row was kept — the header-reconciling prefix must survive")


def test_the_export_is_written_before_anything_is_deleted(tmp_path, monkeypatch,
                                                          capsys):
    """Rule 29's companion: if the delete goes wrong, the record of what was
    about to be removed must already exist on disk."""
    path = _repairable_db(tmp_path, "test_rep_export.db")
    exp = tmp_path / "exp3.json"
    monkeypatch.setattr(sys, "argv",
                        ["repair", "--db", path, "--apply", "--export", str(exp)])
    RLI.main()
    capsys.readouterr()
    import json
    data = json.loads(exp.read_text())
    assert data["engine"] == "sqlite"
    assert data["repairable"][0]["delete"][0]["id"] == 2
    assert "postgresql://" not in json.dumps(data)


@pytest.mark.parametrize("path", _SCRIPTS, ids=lambda p: os.path.basename(p))
def test_the_scripts_report_through_out_not_bare_print(path):
    """A bare `print` of a money figure is a crash waiting for a cp1252 console.
    Asserted on the source so a new one cannot slip in."""
    hits = _scan(path, r"(?<![\w.])print\(")
    assert not hits, ("use out() from _dbcompat so the report cannot die of an "
                      "encoding error:\n" + "\n".join(hits))
