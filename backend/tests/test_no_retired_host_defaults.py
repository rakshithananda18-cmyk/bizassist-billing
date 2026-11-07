# Observed counterexamples on the unfixed code (task 1.1):
#   backend (fails; task 3.2 removes all but routes/admin.py, which is task 7.3):
#     backend/check_cloud_api.py:10           CLOUD_URL = <hf.space>
#     backend/main_groq.py:156                discovery CLOUD_URL = os.getenv("CLOUD_URL", <hf.space>)
#     backend/routes/admin.py:693 and :697    Hugging Face standby probe and its "url"
#     backend/routes/b2b_proxy.py:63          CLOUD_URL = ... or <hf.space>
#     backend/services/realtime.py:12         _CLOUD_URL = os.getenv("CLOUD_URL", <hf.space>)
#     backend/services/sync_worker.py:41      CLOUD_URL = ... or <hf.space>
#     backend/services/telemetry_relay.py:36  CLOUD_URL = os.getenv("BIZASSIST_CLOUD_URL", <hf.space>)
#   desktop (fails; task 3.4): desktop/src/telemetry.js:19
#     CLOUD_URL = process.env.BIZASSIST_CLOUD_URL || <hf.space>
#   scripts (fails; task 3.2): backend/scripts/cloud_cleanup_counters.py:38
#     DEFAULT_CLOUD = ... or <hf.space>
#   dev (xfail): dev/check_cloud_release.py:24 DEFAULT_BILLING_API = <hf.space>,
#     :26 DEFAULT_BILLING_WEB = https://bizassist-billing.vercel.app
#   frontend_task (xfail): frontend-task/src/lib/theme.js:7
#     BILLING_CLOUD_URL = 'https://bizassist-billing.vercel.app'
#   frontend_ai, frontend_admin (xfail): src/utils/handoff.js:3
#     origins = [window.location.origin, billingUrl || 'https://bizassist-billing.vercel.app']
#   frontend_billing (xfail, passes): no retired-host default. Its cloud default
#     is already Cloud Run; the hf.space strings left are comments and
#     url.includes('hf.space') host checks.
#   Allow-listed, not reported: backend/main_groq.py:286 and :294 (_default_origins).
#   <hf.space> = https://rakshit-dev-bizassist.hf.space
"""
tests/test_no_retired_host_defaults.py
======================================
Bug condition exploration for C1 (bugfix 1.32 to 1.34, design Property 1 and
Property 3): no code tree may use the retired hosts as a default.

Retired hosts: the Hugging Face Space (any ``https://*.hf.space`` URL) and the
old billing web host https://bizassist-billing.vercel.app.

What counts as a hit: a retired-host URL inside a string literal of a ``.py``,
``.js``, ``.jsx``, ``.mjs`` or ``.cjs`` file, such as a URL constant or the
fallback operand of ``or``, ``||``, ``??``, ``os.getenv(name, default)`` or
``.get(name, default)``.

What is ignored:
  * comments, and Python docstrings and other bare string statements
    (documentation);
  * test files (``tests/``, ``__tests__/``, ``e2e/`` folders, ``test_*.py``,
    ``*_test.py``, ``conftest.py``, ``*.test.*``, ``*.spec.*``);
  * strings that name the host without a scheme, such as ``"hf.space" in host``.
    Code that only recognises the old host (for example to warn about it) should
    match on the host like that instead of holding the full URL;
  * the entries of ALLOW_LIST: transition trust lists, which keep the old hosts
    trusted while clients move (bugfix 3.10), and documentation strings. A
    trust-list entry never covers a fallback operand, because "trusted until
    the move ends" is different from "used when nothing is configured". C13
    re-checks the CORS and deploy-script lists in part 2.

Trees (one case each): ``backend`` (backend/ without its scripts/ folder),
``desktop`` (desktop/src and desktop/scripts), ``scripts`` (the maintenance
scripts in scripts/ and backend/scripts/, bugfix 1.34), ``dev``, and the src/
folder of each frontend. The ``dev`` and ``frontend_*`` cases are
``xfail(strict=False)`` because their fixes may also need C13 (part 2).

Limits of the JavaScript scan: the lexer separates comments, strings, template
literals and regular expressions but does not parse JSX text, so a URL written
as bare JSX text is read as a comment and not reported.
"""
import ast
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

REPO_ROOT = Path(__file__).resolve().parents[2]

RETIRED_URL = re.compile(
    r"(?i)https?://(?:[a-z0-9-]+\.)*hf\.space\b|https?://bizassist-billing\.vercel\.app\b"
)

CODE_SUFFIXES = {".py", ".js", ".jsx", ".mjs", ".cjs"}
SKIPPED_DIRS = {
    "node_modules", "dist", "build", "out", "coverage", "__pycache__", ".pytest_cache",
    ".venv", "venv", "site-packages", "chroma_db", "logs", ".git",
}
TEST_DIRS = {"tests", "test", "__tests__", "__mocks__", "e2e"}

# tree id -> (folders to scan, folders inside them that belong to another tree)
TREES = {
    "backend": (["backend"], ["backend/scripts"]),
    "desktop": (["desktop/src", "desktop/scripts"], []),
    "scripts": (["scripts", "backend/scripts"], []),
    "dev": (["dev"], []),
    "frontend_billing": (["frontend-billing/src"], []),
    "frontend_task": (["frontend-task/src"], []),
    "frontend_ai": (["frontend-ai/src"], []),
    "frontend_admin": (["frontend-admin/src"], []),
    "landing": (["bizassist-landing/src"], []),
}


@dataclass(frozen=True)
class Allow:
    path: str      # repository-relative path, or "*" for every file
    context: str   # regex for the name the literal is assigned to (or keyword / key)
    reason: str


ALLOW_LIST = (
    # Transition trust lists (CORS origin lists, Billing-origin trust lists).
    Allow("backend/main_groq.py", r"^_default_origins$",
          "CORS origin list: transition origins stay trusted (3.10); C13 trims it in part 2"),
    Allow("frontend-task/src/lib/theme.js", r"(?i)origins$",
          "Billing-origin trust list (C10.1, 3.10)"),
    Allow("frontend-ai/src/utils/handoff.js", r"(?i)origins$",
          "Billing-origin trust list (C11.1, 3.7, 3.10)"),
    Allow("frontend-admin/src/utils/handoff.js", r"(?i)origins$",
          "Billing-origin trust list (C11.1, 3.7, 3.10)"),
    # Documentation: command-line help text may show the old host as an example.
    Allow("*", r"^(help|description|epilog|usage)$", "command-line help text"),
    Allow("dev/check_cloud_release.py", r"^(DEFAULT_FORWARDER|forwarder)$", "Compatibility forwarder is an explicit release check target"),
)


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    url: str
    context: str
    fallback: bool

    def allowed(self) -> bool:
        if self.fallback:
            return False
        return any(
            entry.path in ("*", self.path) and re.search(entry.context, self.context)
            for entry in ALLOW_LIST
        )

    def __str__(self) -> str:
        kind = "fallback" if self.fallback else "value"
        return f"{self.path}:{self.line}: {self.url} ({kind} in {self.context})"


# ── Python ────────────────────────────────────────────────────────────────────

_FALLBACK_CALLS = {"getenv", "get", "setdefault", "pop"}


def _target_name(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _target_name(node.value)
    if isinstance(node, (ast.Tuple, ast.List)):
        return ",".join(filter(None, (_target_name(e) for e in node.elts)))
    return ""


def _python_context(node, parents) -> tuple:
    """Return (context name, used as a fallback) for a string constant."""
    fallback = False
    child = node
    while child in parents:
        parent = parents[child]
        if isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.Or):
            if any(v is child for v in parent.values[1:]):
                fallback = True
        elif isinstance(parent, ast.IfExp) and parent.orelse is child:
            fallback = True
        elif isinstance(parent, ast.Call):
            func = parent.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in _FALLBACK_CALLS and len(parent.args) > 1 and parent.args[1] is child:
                fallback = True
        elif isinstance(parent, ast.keyword):
            return (parent.arg or "**"), (fallback or parent.arg == "default")
        elif isinstance(parent, ast.Dict):
            for key, value in zip(parent.keys, parent.values):
                if value is child and isinstance(key, ast.Constant) and isinstance(key.value, str):
                    return key.value, fallback
        elif isinstance(parent, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
            return ",".join(filter(None, (_target_name(t) for t in targets))) or "<assignment>", fallback
        elif isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return f"<{parent.name}>", fallback
        elif isinstance(parent, ast.stmt):
            return f"<{type(parent).__name__.lower()}>", fallback
        child = parent
    return "<module>", fallback


def _is_bare_string_statement(node, parents) -> bool:
    child = node
    while child in parents and isinstance(parents[child], (ast.JoinedStr, ast.FormattedValue)):
        child = parents[child]
    return isinstance(parents.get(child), ast.Expr)


def _python_hits(text: str, rel: str) -> list:
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # Cannot be imported anyway; fall back to a plain line scan without comments.
        hits = []
        for number, line in enumerate(lines, 1):
            code = line.split("#", 1)[0]
            for m in RETIRED_URL.finditer(code):
                hits.append(Hit(rel, number, m.group(0), "<unparsed>", False))
        return hits

    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        urls = [m.group(0) for m in RETIRED_URL.finditer(node.value)]
        if not urls or _is_bare_string_statement(node, parents):
            continue
        context, fallback = _python_context(node, parents)
        first = getattr(node, "lineno", 1)
        last = getattr(node, "end_lineno", first) or first
        for url in urls:
            number = next((n for n in range(first, last + 1)
                           if n <= len(lines) and url in lines[n - 1]), first)
            hits.append(Hit(rel, number, url, context, fallback))
    return hits


# ── JavaScript ────────────────────────────────────────────────────────────────

_JS_REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
_JS_REGEX_KEYWORDS = {"return", "typeof", "instanceof", "in", "of", "new", "delete",
                      "void", "throw", "case", "do", "else", "yield", "await"}


def _js_lex(src: str):
    """Yield (kind, start, end) for the comments and string literals of JS/JSX source."""
    i, n = 0, len(src)
    last = ""
    while i < n:
        c = src[i]
        if c in " \t\r\n":
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            yield "comment", i, j
            i = j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            yield "comment", i, j
            i = j
            continue
        if c in "'\"":
            j = i + 1
            while j < n and src[j] not in (c, "\n"):
                j += 2 if src[j] == "\\" else 1
            j = min(j + 1, n)
            yield "string", i, j
            i, last = j, "value"
            continue
        if c == "`":
            j, depth = i + 1, 0
            while j < n:
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if depth == 0 and ch == "`":
                    break
                if src.startswith("${", j):
                    depth += 1
                    j += 2
                    continue
                if depth and ch == "}":
                    depth -= 1
                j += 1
            j = min(j + 1, n)
            yield "string", i, j
            i, last = j, "value"
            continue
        if c == "/" and not (i > 0 and src[i - 1] == "<"):
            regex_allowed = (last == "" or last in _JS_REGEX_AFTER
                             or (last.startswith("word:") and last[5:] in _JS_REGEX_KEYWORDS))
            if regex_allowed:
                j, in_class = i + 1, False
                while j < n and src[j] != "\n":
                    ch = src[j]
                    if ch == "\\":
                        j += 2
                        continue
                    if ch == "[":
                        in_class = True
                    elif ch == "]":
                        in_class = False
                    elif ch == "/" and not in_class:
                        break
                    j += 1
                j += 1
                while j < n and (src[j].isalnum() or src[j] == "_"):
                    j += 1
                i, last = j, "value"
                continue
        if c.isalnum() or c in "_$":
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            word = src[i:j]
            last = "value" if word[0].isdigit() else "word:" + word
            i = j
            continue
        last = c
        i += 1


_JS_DECLARATION = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=")
_JS_ASSIGNMENT = re.compile(
    r"^\s*(?:[A-Za-z_$][\w$]*\.)*([A-Za-z_$][\w$]*)\s*(?:\|\||\?\?|&&)?=(?![=>])")
_JS_PROPERTY = re.compile(
    r"^\s*(?:([A-Za-z_$][\w$]*)|'([A-Za-z_$][\w$-]*)'|\"([A-Za-z_$][\w$-]*)\")\s*:(?!:)")
_JS_FUNCTION = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)")
_JS_CONTINUES = ("[", "(", "{", ",", "=", "||", "??", "&&", "+", "?", ":")


def _js_context(code_lines: list, index: int) -> str:
    """Name of the declaration, assignment or property that holds line `index`."""
    while index >= 0:
        line = code_lines[index]
        for pattern in (_JS_DECLARATION, _JS_ASSIGNMENT, _JS_PROPERTY):
            m = pattern.match(line)
            if m:
                return next(g for g in m.groups() if g)
        m = _JS_FUNCTION.match(line)
        if m:
            return f"<{m.group(1)}>"
        index -= 1
        if index < 0 or not code_lines[index].rstrip().endswith(_JS_CONTINUES):
            break
    return "<expression>"


def _js_hits(text: str, rel: str) -> list:
    tokens = list(_js_lex(text))
    code = list(text)
    for kind, start, end in tokens:
        if kind == "comment":
            for k in range(start, end):
                if code[k] != "\n":
                    code[k] = " "
    code = "".join(code)
    code_lines = code.split("\n")
    hits = []
    for kind, start, end in tokens:
        if kind != "string":
            continue
        for m in RETIRED_URL.finditer(text, start, end):
            index = code.count("\n", 0, start)
            before = code[:start].rstrip()
            fallback = before.endswith("||") or before.endswith("??")
            hits.append(Hit(rel, index + 1 + text.count("\n", start, m.start()), m.group(0),
                            _js_context(code_lines, index), fallback))
    return hits


# ── Tree walk ─────────────────────────────────────────────────────────────────

def _is_test_file(rel_parts: tuple) -> bool:
    name = rel_parts[-1]
    if any(part in TEST_DIRS for part in rel_parts[:-1]):
        return True
    return bool(
        name == "conftest.py"
        or re.match(r"^test_.*\.py$", name)
        or re.match(r"^.*_test\.py$", name)
        or re.search(r"\.(test|spec)\.[cm]?jsx?$", name)
        or re.match(r"^setupTests\.[cm]?jsx?$", name)
    )


def _scan_tree(tree_id: str) -> tuple:
    folders, excluded = TREES[tree_id]
    excluded_paths = [(REPO_ROOT / e).resolve() for e in excluded]
    roots = [REPO_ROOT / f for f in folders if (REPO_ROOT / f).is_dir()]
    hits, scanned = [], 0
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath).resolve()
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIPPED_DIRS and (here / d).resolve() not in excluded_paths
            ]
            for filename in filenames:
                path = here / filename
                if path.suffix not in CODE_SUFFIXES:
                    continue
                rel_parts = path.relative_to(REPO_ROOT).parts
                if _is_test_file(rel_parts):
                    continue
                scanned += 1
                text = path.read_text(encoding="utf-8-sig", errors="replace")
                if not RETIRED_URL.search(text):
                    continue
                rel = "/".join(rel_parts)
                found = _python_hits(text, rel) if path.suffix == ".py" else _js_hits(text, rel)
                hits.extend(h for h in found if not h.allowed())
    return roots, scanned, sorted(set(hits), key=lambda h: (h.path, h.line, h.url))


@pytest.mark.parametrize("tree_id", [
    pytest.param("backend", id="backend"),
    pytest.param("desktop", id="desktop"),
    pytest.param("scripts", id="scripts"),
    pytest.param("dev", id="dev"),
    pytest.param("frontend_billing", id="frontend_billing"),
    pytest.param("frontend_task", id="frontend_task"),
    pytest.param("frontend_ai", id="frontend_ai"),
    pytest.param("frontend_admin", id="frontend_admin"),
    pytest.param("landing", id="landing"),
])
def test_no_retired_host_defaults(tree_id):
    """Property 1 / Property 3: no tree falls back to, or hard-codes, a retired host.

    **Validates: Requirements 1.32, 1.33, 1.34 (expected 2.32, 2.33, 2.34)**
    """
    roots, scanned, hits = _scan_tree(tree_id)
    if not roots:
        pytest.skip(f"{tree_id}: none of {TREES[tree_id][0]} exists in this checkout")
    assert scanned, f"{tree_id}: no code files found under {TREES[tree_id][0]}"
    assert not hits, (
        f"{tree_id}: {len(hits)} retired-host default(s) outside the allow-list:\n  "
        + "\n  ".join(str(h) for h in hits)
    )
