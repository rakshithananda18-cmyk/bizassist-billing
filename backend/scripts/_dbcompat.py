"""
scripts/_dbcompat.py — one thin DB-API layer so the money scripts run on BOTH
SQLite (local) and PostgreSQL (the Hugging Face cloud).
==============================================================================

WHY THIS EXISTS
---------------
`audit_money_integrity.py` and `repair_line_items_by_invariant.py` both opened
`sqlite3.connect(...)` directly. Every integrity claim in the strategic review is
therefore a claim about the LOCAL database only — and the 2026-07-27 cloud boot
log showed the overfill guard reporting **31 invoices and 2 b2b_orders on
Postgres** holding more line value than was billed, which no tool in the tree
could audit, let alone repair.

THE HAZARD THIS MODULE IS SHAPED BY
-----------------------------------
Finding N4b-PG (§63): a guard verified on SQLite alone shipped
`ROUND(<double precision>, 2)`, which does not exist on Postgres, and took every
subsequent migration step down with it. The lesson (rules 51 and 59) is not "add
a cast" — it is **prefer SQL that calls no dialect-specific function at all**,
because a cast is a second assumption that also cannot be executed here.

So this module is deliberately small. It handles only the differences that
cannot be avoided:

  * **paramstyle** — SQLite `?` vs psycopg2 `%s`, plus the `%` escaping that
    psycopg2 requires once parameters are present.
  * **row access** — `sqlite3.Row` supports `r["col"]` and `r[0]`; psycopg2's
    default cursor gives tuples only. Both are normalised to one `Row` type.
  * **catalogue lookups** — `sqlite_master` vs `information_schema`.
  * **integrity checks** — `PRAGMA integrity_check` / `foreign_key_check` exist
    only on SQLite; on Postgres foreign keys are enforced by the engine on every
    write, so the equivalent statement is different and must be reported as such
    rather than silently returning "clean" (rule 33).
  * **read-only enforcement** — SQLite via `?mode=ro`, Postgres via
    `default_transaction_read_only`, so an audit run cannot write even by
    accident. This matters more on the cloud than locally.

Everything else — the arithmetic, the tolerances, the invariants — stays in
plain portable SQL in the calling scripts.

WHAT IS NOT PROVED
------------------
There is no PostgreSQL server in CI or in the sandbox this was written in.
`tests/test_dbcompat.py` proves the translation and row behaviour against a fake
connection that reproduces psycopg2's paramstyle and abort-on-error semantics,
and `test_sql_portability.py` gates the scripts' SQL against the constructs known
to differ. Neither is a substitute for one real run against the cloud replica.
Treat the first Postgres run as the verification, and run the AUDIT (read-only)
before the repair.
"""
from __future__ import annotations

import os
import sys

SQLITE = "sqlite"
POSTGRES = "postgresql"


# ─────────────────────────────────────────────────────────────────────────────
# Console output that cannot kill the report
# ─────────────────────────────────────────────────────────────────────────────

_TRANSLIT = {
    "₹": "Rs ",   # ₹
    "—": "-",     # em dash
    "–": "-",     # en dash
    "→": "->",    # →
    "…": "...",   # …
    "·": "*",     # ·
    "─": "-",     # box drawing
    "█": "#",
    "⚠": "!",     # ⚠
}


def _stdout_can_encode(sample="₹") -> bool:
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        sample.encode(enc)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


_ASCII_ONLY = None


def out(text: str = "") -> None:
    """Print a report line, transliterating if the console cannot take it.

    A MONEY AUDIT MUST NOT DIE OF A CONSOLE CODE PAGE.
    On the first real cloud run this report reached section B — having already
    found 63 documents with no journal entry — and then raised

        UnicodeEncodeError: 'charmap' codec can't encode character '\\u20b9'

    because a Windows console is cp1252 and the amounts are printed with `₹`.
    Sections C through J were never rendered. The findings existed; the operator
    could not see them. That is the same failure mode as a check that reports
    nothing: an unreadable answer and no answer are the same answer.

    So: `₹` becomes `Rs` and the dashes become ASCII when — and only when — the
    stream cannot carry them. A UTF-8 terminal, and any redirect to a file, keep
    the real glyphs. `errors="replace"` underneath means even an unforeseen
    character degrades to `?` rather than terminating the run.
    """
    global _ASCII_ONLY
    if _ASCII_ONLY is None:
        _ASCII_ONLY = not _stdout_can_encode()
    if _ASCII_ONLY:
        for bad, good in _TRANSLIT.items():
            text = text.replace(bad, good)
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(enc, "replace").decode(enc, "replace"))


def use_utf8_stdout() -> None:
    """Prefer real UTF-8 output where the stream supports being reconfigured.

    Called at the top of each script. On Python 3.7+ this turns a cp1252 console
    into one that can carry `₹` outright; where it cannot, `out()` above still
    guarantees the report finishes.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            # Acceptable swallow (rule 13): this is a best-effort improvement to
            # legibility, and out() is the actual guarantee. Nothing about the
            # audit's correctness depends on it.
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Rows
# ─────────────────────────────────────────────────────────────────────────────

class Row:
    """A result row addressable by name OR position, on either driver.

    `sqlite3.Row` already does both; psycopg2's default cursor returns plain
    tuples. Rather than depend on `RealDictCursor` (name-only, so `r[0]` breaks)
    or `NamedTupleCursor` (which mangles column names that are not identifiers),
    rows are built from `cursor.description` so both access styles work
    identically on both engines.
    """
    __slots__ = ("_v", "_i")

    def __init__(self, values, index):
        self._v = values
        self._i = index

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return self._v[self._i[key]]
            except KeyError:
                raise KeyError(
                    f"no column {key!r} in row; columns are "
                    f"{list(self._i)}") from None
        return self._v[key]

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, IndexError):
            return default

    def keys(self):
        return list(self._i)

    def __iter__(self):
        return iter(self._v)

    def __len__(self):
        return len(self._v)

    def __repr__(self):
        return "Row(" + ", ".join(f"{k}={self._v[i]!r}"
                                  for k, i in self._i.items()) + ")"


# ─────────────────────────────────────────────────────────────────────────────
# SQL translation
# ─────────────────────────────────────────────────────────────────────────────

def translate(sql: str, dialect: str, has_params: bool) -> str:
    """Rewrite `?` placeholders to `%s` for psycopg2, quoting-aware.

    Two things go wrong if this is done with `str.replace`:

      1. A `?` inside a string literal is data, not a placeholder. None of our
         SQL has one today, which is exactly why a naive replace would survive
         review and then corrupt a query written next year.
      2. psycopg2 treats `%` as its own format character. `LIKE 'Initial payment
         for invoice %'` is fine when no parameters are passed, and raises
         `IndexError: unsupported format character` the moment they are. So `%`
         must be doubled — but ONLY when parameters are present, because
         psycopg2 does no interpolation at all otherwise.

    SQLite needs no translation; it is returned unchanged so the local path is
    byte-identical to what it has always run.
    """
    if dialect != POSTGRES:
        return sql

    out = []
    in_str = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if in_str:
            if ch == "'":
                # '' is an escaped quote inside a literal, not the end of it.
                if i + 1 < n and sql[i + 1] == "'":
                    out.append("''")
                    i += 2
                    continue
                in_str = False
            if ch == "%" and has_params:
                out.append("%%")
                i += 1
                continue
            out.append(ch)
        else:
            if ch == "'":
                in_str = True
                out.append(ch)
            elif ch == "?":
                out.append("%s")
            elif ch == "%" and has_params:
                out.append("%%")
            else:
                out.append(ch)
        i += 1
    return "".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Connection
# ─────────────────────────────────────────────────────────────────────────────

class Conn:
    """A minimal, uniform connection over sqlite3 or psycopg2."""

    def __init__(self, raw, dialect: str, label: str, readonly: bool):
        self._raw = raw
        self.dialect = dialect
        self.label = label
        self.readonly = readonly

    # -- queries ------------------------------------------------------------
    def execute(self, sql, params=()):
        cur = self._raw.cursor()
        # THE EMPTY-PARAMETER CASE IS DIALECT-SPECIFIC, in opposite directions.
        #
        # psycopg2 skips its format pass ONLY when `vars is None`. Handed an
        # EMPTY tuple it still interpolates, so a literal `%` in the SQL is read
        # as a format specifier:
        #
        #     SELECT * FROM invoice_payments
        #      WHERE note LIKE 'Initial payment for invoice %'
        #     -> IndexError: tuple index out of range
        #
        # which is what the first real cloud run hit, on audit section A.
        #
        # sqlite3 is the reverse: it rejects `None` outright with
        # `ValueError: parameters are of unsupported type` and wants `()`.
        #
        # So neither value is portable and the layer has to choose per engine —
        # which is precisely what it exists for. Passing `()` to both looked
        # correct locally for the same reason N4b-PG did: only one dialect was
        # ever exercised.
        translated = translate(sql, self.dialect, bool(params))
        if self.dialect == POSTGRES:
            cur.execute(translated, params if params else None)
        else:
            cur.execute(translated, params or ())
        return _Result(cur)

    def scalar(self, sql, params=(), default=None):
        r = self.execute(sql, params).fetchone()
        if r is None:
            return default
        v = r[0]
        return default if v is None else v

    # -- transactions -------------------------------------------------------
    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        try:
            self._raw.close()
        except Exception:
            pass

    # -- introspection ------------------------------------------------------
    def table_exists(self, name: str) -> bool:
        if self.dialect == SQLITE:
            return self.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,)).fetchone() is not None
        return self.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog','information_schema') "
            "AND table_name = ?", (name,)).fetchone() is not None

    def integrity_report(self) -> dict:
        """-> {'integrity': str, 'fk_violations': int|None, 'note': str}

        `fk_violations` is None when the engine cannot be asked — which is a
        DIFFERENT answer from 0 and must never be rendered as 'clean' (rule 33,
        and rule 63: absent is not zero).
        """
        if self.dialect == SQLITE:
            integ = self.scalar("PRAGMA integrity_check", default="unknown")
            fk = len(self.execute("PRAGMA foreign_key_check").fetchall())
            return {"integrity": integ, "fk_violations": fk,
                    "note": "PRAGMA integrity_check + foreign_key_check"}
        # Postgres validates every FK on write and has no whole-database
        # equivalent of integrity_check. A NOT VALID constraint is the one case
        # where rows may violate a declared FK, so that is what is worth
        # reporting; anything else cannot be out of step by construction.
        notvalid = self.execute(
            "SELECT conrelid::regclass::text AS child, conname "
            "FROM pg_constraint WHERE contype='f' AND NOT convalidated"
        ).fetchall()
        return {
            "integrity": "n/a (engine-enforced)",
            "fk_violations": len(notvalid),
            "note": ("foreign keys are enforced by the engine on every write; "
                     "reported figure counts NOT VALID constraints, which are "
                     "the only way a declared FK can hold violating rows"),
        }


class _Result:
    """Cursor wrapper that yields `Row` and is iterable exactly once."""

    def __init__(self, cur):
        self._cur = cur
        desc = cur.description or []
        self._index = {d[0]: i for i, d in enumerate(desc)}

    @property
    def rowcount(self) -> int:
        """Rows affected by a DML statement.

        Both drivers expose this; the wrapper hid it, and the omission surfaced
        as `'_Result' object has no attribute 'rowcount'` from inside the
        repair's DELETE — after the export was written. The transaction rolled
        back cleanly, which is the behaviour the verify-before-commit rework was
        added for, but the attribute belongs here.
        """
        return self._cur.rowcount

    def _wrap(self, t):
        return None if t is None else Row(t, self._index)

    def fetchone(self):
        return self._wrap(self._cur.fetchone())

    def fetchall(self):
        return [self._wrap(t) for t in self._cur.fetchall()]

    def __iter__(self):
        for t in self._cur:
            yield self._wrap(t)


# ─────────────────────────────────────────────────────────────────────────────
# Opening
# ─────────────────────────────────────────────────────────────────────────────

def ensure(con):
    """Accept either a `Conn` or a bare DB-API connection.

    `find_offenders`, `money_snapshot` and `audit` are a public surface: tests
    and one-off console sessions hand them a plain `sqlite3.connect(...)`, and
    that was valid for the whole life of these scripts. Introducing the compat
    layer must not silently break every existing caller — so the entry points
    normalise instead of demanding the wrapper.

    Detected by capability, not by `isinstance`: a `psycopg2` connection is
    equally welcome, and duck-typing keeps this module free of driver imports.
    """
    if isinstance(con, Conn):
        return con
    dialect = POSTGRES if con.__class__.__module__.startswith("psycopg") else SQLITE
    return Conn(con, dialect, f"<{type(con).__name__}>", readonly=False)


def is_postgres_target(target: str) -> bool:
    return str(target).startswith(("postgresql://", "postgres://",
                                   "postgresql+psycopg2://"))


def connect(target: str, *, readonly: bool = True) -> Conn:
    """Open `target`, which is either a SQLite file path or a Postgres URL.

    `readonly` is enforced by the ENGINE, not by convention: SQLite gets
    `?mode=ro`, Postgres gets `default_transaction_read_only`. An audit that
    cannot write is worth more on a production database than an audit that
    merely intends not to.
    """
    # Checked for BOTH engines and before the scheme is examined: a placeholder
    # with no `postgresql://` prefix would otherwise be treated as a file path
    # and reported as `database not found`, which is true and useless.
    if _looks_like_a_placeholder(target):
        sys.exit(_placeholder_message(target))
    if is_postgres_target(target):
        return _connect_postgres(target, readonly)
    return _connect_sqlite(target, readonly)


def _placeholder_message(url: str) -> str:
    return (
        f"\n  The connection string still contains the example placeholders:\n"
        f"      {_redact(url)}\n\n"
        f"  Replace it with the REAL value. It lives in your Hugging Face\n"
        f"  Space secrets as DATABASE_URL (Supabase pooler), and looks like:\n"
        f"      postgresql://postgres.<ref>:<password>"
        f"@<region>.pooler.supabase.com:5432/postgres\n\n"
        f"  PowerShell:\n"
        f"      $env:BIZASSIST_AUDIT_DATABASE_URL = \"<the real URL>\"\n\n"
        f"  Do not paste the real URL into a file that gets committed.\n")


def _readonly_uri(path: str) -> str:
    """A SQLite `file:` URI built by `Path.as_uri()` rather than by f-string.

    HARDENING, and I am labelling it accurately rather than claiming a fix I did
    not prove. The `unable to open database file` reported on 2026-07-27 was
    caused by a script resolving its default path to the wrong DIRECTORY; the
    file genuinely was not there, and `mode=ro` does not create one. That is the
    confirmed cause and it is fixed at the call site.

    Separately: `f"file:{path}?mode=ro"` is not a correct way to build the URI.
    The working copy of this project lives at

        D:\\Dev Workspace\\ai_agent_lab_google(1)\\bizassist-billing\\backend

    — a space, parentheses, and backslashes, none of which are valid unescaped
    in a URI. Tested here on Linux, the naive form happens to open a path with
    spaces anyway, so I have NOT demonstrated that it fails on Windows and will
    not assert that it does. `Path.as_uri()` percent-encodes and forward-slashes
    correctly on both platforms, which removes the question rather than
    answering it.

    Worth stating plainly: the read-only SQLite path had never been executed on
    the owner's own machine before today — every SQLite run in this session used
    a /tmp path, and every Windows run used Postgres.
    """
    from pathlib import Path
    return Path(os.path.abspath(path)).as_uri() + "?mode=ro"


def _connect_sqlite(path: str, readonly: bool) -> Conn:
    import sqlite3
    if not os.path.exists(path):
        sys.exit(
            f"database not found: {os.path.abspath(path)}\n"
            f"Pass --db <path-or-postgres-url>. Refusing to guess or create "
            f"one — a money script that opens the wrong database reports "
            f"'nothing to repair' and is believed.")
    if readonly:
        raw = sqlite3.connect(_readonly_uri(path), uri=True)
    else:
        raw = sqlite3.connect(path)
    return Conn(raw, SQLITE, os.path.abspath(path), readonly)


# The literal placeholders printed in the runbook. Pasting the example DSN
# unedited is the single commonest way this goes wrong, and psycopg2's answer —
# `could not translate host name "HOST"` under a nine-frame traceback — does not
# say "you forgot to fill in the URL".
_PLACEHOLDERS = ("USER", "PASS", "PASSWORD", "HOST", "DBNAME", "YOUR_",
                 "<", "project-ref", "SUPABASE_DATABASE_URL_FROM_SECRET")


def _looks_like_a_placeholder(url: str) -> bool:
    """True for a connection string that was copied from the runbook unedited.

    Checked on the WHOLE target, before the scheme is even parsed. An earlier
    version split on `://` first and returned False for
    `<SUPABASE_DATABASE_URL_FROM_SECRET>` — which has no scheme, so it fell
    through to the SQLite branch and reported `database not found`. Technically
    true, and no help at all.
    """
    if not url:
        return False
    if "<" in url and ">" in url:
        return True
    tail = url.split("://", 1)[1] if "://" in url else url
    creds, _, host = tail.partition("@")
    parts = set(creds.replace(":", " ").split()) | set(
        host.replace(":", " ").replace("/", " ").split())
    return any(p in parts for p in _PLACEHOLDERS)


_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]", "host.docker.internal")


def _is_local(url: str) -> bool:
    """Host-only, handling a bracketed IPv6 literal.

    Splitting on ':' to drop the port turns `[::1]:5432` into `[`, so an IPv6
    loopback was classified as remote and had TLS forced onto it. The brackets
    exist precisely because the address itself contains colons.
    """
    tail = url.split("://", 1)[-1]
    hostpart = tail.partition("@")[2] or tail
    hostpart = hostpart.split("/")[0].split("?")[0]
    if hostpart.startswith("["):
        host = hostpart[1:hostpart.index("]")] if "]" in hostpart else hostpart[1:]
    else:
        host = hostpart.split(":")[0]
    return host in tuple(h.strip("[]") for h in _LOCAL_HOSTS)


def _with_sslmode(url: str) -> str:
    """Force TLS for any REMOTE Postgres, unless the caller chose a mode.

    psycopg2 defaults to `sslmode=prefer`: it tries TLS and **silently falls
    back to plaintext** if the server does not offer it. That default is wrong
    for what this tool does — it carries a production credential across the
    public internet to a Supabase pooler, and "prefer" means a downgrade is
    invisible. `require` costs nothing against any managed provider (they all
    mandate TLS anyway) and removes the silent-downgrade case.

    Local sockets are left alone: a developer Postgres on localhost usually has
    no certificate, and forcing TLS there would break the one setup where the
    credential never leaves the machine.
    """
    if "sslmode=" in url or _is_local(url):
        return url
    return url + ("&" if "?" in url else "?") + "sslmode=require"


def _enforce_readonly(raw, url):
    """Make the SESSION read-only, and refuse to continue if that is impossible.

    FAIL CLOSED (rules 17-18). The point of the audit being read-only is that it
    cannot damage a production database — so if the guarantee cannot be
    established, the right answer is to stop, not to carry on unprotected while
    the banner still claims `mode: read-only`.

    This matters specifically because of PgBouncer: Supabase's TRANSACTION-mode
    pooler (port 6543) multiplexes sessions and rejects session-level `SET`.
    Against that endpoint `SET default_transaction_read_only = on` fails, and
    without this check the tool would print `mode: read-only` over a session
    that was nothing of the kind.
    """
    try:
        cur = raw.cursor()
        cur.execute("SET default_transaction_read_only = on")
        cur.execute("SHOW default_transaction_read_only")
        got = cur.fetchone()[0]
        cur.close()
        raw.commit()
    except Exception as e:
        raw.close()
        sys.exit(
            f"\n  Could not put the session into READ-ONLY mode:\n"
            f"      {str(e).strip()}\n\n"
            f"  Refusing to continue. This tool's safety property is that it\n"
            f"  CANNOT write to the database it is pointed at, and that could\n"
            f"  not be established here.\n\n"
            f"  If you are on the TRANSACTION pooler (port 6543), use the\n"
            f"  SESSION pooler on port 5432 instead — PgBouncer in transaction\n"
            f"  mode does not allow session-level SET.\n\n"
            f"  Nothing was read and nothing was changed.\n")
    if str(got).lower() not in ("on", "true", "t"):
        raw.close()
        sys.exit(
            f"\n  The server did not accept read-only mode "
            f"(default_transaction_read_only={got!r}).\n"
            f"  Refusing to continue.\n")


def _connect_postgres(url: str, readonly: bool) -> Conn:
    try:
        import psycopg2
    except ImportError:
        sys.exit(
            "psycopg2 is not installed, so this database cannot be opened.\n"
            "  pip install psycopg2-binary")

    if _looks_like_a_placeholder(url):        # belt; connect() is the braces
        sys.exit(_placeholder_message(url))

    url = _with_sslmode(url.replace("postgresql+psycopg2://", "postgresql://"))

    # Read-only as a STARTUP option, not just a SET — the transaction-pooler
    # problem.
    #
    # Supabase's port 6543 is PgBouncer in TRANSACTION mode: the server
    # connection goes back to the pool after every transaction, so a session
    # `SET` can be silently lost for the next query, which may land on a
    # different backend. `SET` + `SHOW` therefore verifies only the instant it
    # runs — exactly the "true when measured, false later" shape this review
    # keeps finding.
    #
    # A startup `options` string is part of the connection handshake and forms
    # part of PgBouncer's pool key, so every server connection serving this
    # client carries it. Falls back to the plain URL if the server rejects the
    # option, because being unable to connect at all is worse — and the SET+SHOW
    # check below still runs either way.
    startup = None if "options=" in url else "-c default_transaction_read_only=on"
    raw = None
    if readonly and startup:
        try:
            raw = psycopg2.connect(url, options=startup)
        except Exception as e:
            # Only an option-related rejection is worth retrying without it.
            # Anything else (bad host, bad password, paused project) is the real
            # failure and must be reported as itself, not masked by a retry.
            if "option" not in str(e).lower():
                _fail_connect(url, e)
    if raw is None:
        try:
            raw = psycopg2.connect(url)
        except Exception as e:
            _fail_connect(url, e)

    if readonly:
        # Verified, not merely requested — see _enforce_readonly. Runs before
        # any query, so no statement in this process can write.
        _enforce_readonly(raw, url)
    return Conn(raw, POSTGRES, _redact(url), readonly)


def _fail_connect(url, e):
    """Turn a driver exception into an answer. A stack trace is not one.

    Each failure that actually happens has a different next step, so each is
    named, and the password never appears.
    """
    msg = str(e).strip()
    low = msg.lower()
    hint = ""
    if "could not translate host name" in low or "name or service" in low:
        hint = ("The host does not resolve. Check the host part of the URL, "
                "and that you are online.")
    elif "password authentication failed" in low or "authentication" in low:
        hint = ("The credentials were rejected. Re-copy DATABASE_URL from the "
                "Space secrets; a password containing @ / : / # must be "
                "percent-encoded in a URL (@ becomes %40).")
    elif "server closed the connection unexpectedly" in low:
        hint = (
            "TCP reached the pooler and it hung up during the handshake. That "
            "is almost never a bad password:\n"
            "      1. Try the other pooler port. Both exist -- 5432 (session) "
            "and 6543 (transaction) -- and a project may serve only one of "
            "them. On 2026-07-27, 5432 hung up here and 6543 connected.\n"
            "      2. The Supabase project may be PAUSED. The pooler still "
            "accepts TCP while paused; resume it from the dashboard.\n"
            "      3. Network restrictions, if an IP allow-list is configured.\n"
            "    SSL is already forced by this tool, so it is not that.")
    elif "timeout" in low or "connection refused" in low:
        hint = ("Reached the network but not the database. Check the port and "
                "any firewall or VPN.")
    sys.exit(f"\n  Could not connect to {_redact(url)}\n"
             f"      {msg}\n"
             + (f"\n  {hint}\n" if hint else "")
             + "\n  Nothing was read and nothing was changed.\n")


def _redact(url: str) -> str:
    """A DSN with a password must never reach a log or a printed banner."""
    try:
        head, tail = url.split("://", 1)
        if "@" in tail:
            creds, host = tail.split("@", 1)
            user = creds.split(":", 1)[0]
            return f"{head}://{user}:***@{host}"
    except Exception:
        pass
    return url


def resolve_target(arg: str | None) -> str:
    """Where to point, in priority order: explicit --db, then the environment.

    `BIZASSIST_AUDIT_DATABASE_URL` is read INSTEAD of `DATABASE_URL` on purpose.
    A money script that silently inherits whatever the app is pointed at is one
    stray shell export away from repairing production while you believe you are
    on a copy.
    """
    if arg:
        return arg
    env = os.getenv("BIZASSIST_AUDIT_DATABASE_URL")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "bizassist.db")
