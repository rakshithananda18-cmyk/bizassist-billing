"""
logging_config.py
=================
One place to configure logging for the whole BizAssist backend.

Goals
-----
* Easy to identify: every line shows the COMPONENT (the module's logger,
  stripped of the shared "bizassist." prefix) in an aligned column, plus a
  short [TAG] inside the message marking the sub-step / decision.
* Easy to tune: level comes from the LOG_LEVEL env var (default INFO).
* Quiet by default: noisy third-party libraries are pinned to WARNING so the
  app's own logs are readable.

Usage
-----
    # once, at startup (main_groq.py):
    from logging_config import configure_logging
    configure_logging()

    # in every module:
    from logging_config import get_logger
    logger = get_logger(__name__)          # -> "bizassist.services.ai_router"
    logger.info(f"{TAG.DIRECT} handler={key}")

Sample output
-------------
    12:34:56 INFO   services.ai_router      [DIRECT] handler=invoice_count
    12:34:56 WARN   services.rate_limiter   [RATELIMIT] user 7 hit daily limit
"""
import logging
import os
import sys

# ── Canonical message tags ──────────────────────────────────────────
# Use these so every component logs with a consistent, greppable prefix.
# `grep "\[DIRECT\]"` should surface every DIRECT decision, app-wide.


class TAG:
    # request routing / tiers
    ROUTER         = "[ROUTER]"          # query_router classify decisions
    CONVERSATIONAL = "[CONVERSATIONAL]"
    CACHE          = "[CACHE]"           # cache hit/miss/invalidate (context_cache)
    DIRECT         = "[DIRECT]"          # DB-only answer
    INTENT         = "[INTENT]"          # intent-first promotion / intents.py
    AI_SIMPLE      = "[AI_SIMPLE]"
    AI_COMPLEX     = "[AI_COMPLEX]"
    # request helpers
    TOKENS         = "[TOKENS]"          # token accounting
    RATELIMIT      = "[RATELIMIT]"
    POLISH         = "[POLISH]"
    CHART          = "[CHART]"
    CHAT           = "[CHAT]"            # chat-message persistence
    HANDLER        = "[HANDLER]"         # direct_query_handler
    TOOL           = "[TOOL]"            # tool execution
    # agent graph
    AGENT          = "[AGENT]"
    PLANNER        = "[PLANNER]"
    SYNTH          = "[SYNTH]"
    # data / IO
    EMBED          = "[EMBED]"           # local embedding model
    CHROMA         = "[CHROMA]"          # vector store ops
    PDF            = "[PDF]"
    PARSER         = "[PARSER]"
    MAPPER         = "[MAPPER]"          # column_mapper
    UPLOAD         = "[UPLOAD]"
    # background / delivery
    SCHED          = "[SCHED]"
    ALERT          = "[ALERT]"
    EMAIL          = "[EMAIL]"
    NOTIFY         = "[NOTIFY]"
    # domain
    ACTION         = "[ACTION]"
    AUTH           = "[AUTH]"
    ADMIN          = "[ADMIN]"
    RECS           = "[RECS]"


# Third-party loggers that spam INFO/DEBUG — keep them at WARNING.
_NOISY_LIBS = (
    "httpx", "httpcore", "urllib3", "chromadb", "sentence_transformers",
    "apscheduler", "groq", "anthropic", "asyncio", "watchfiles", "uvicorn.access",
)

# ANSI colours for the level column (only used on a TTY).
_LEVEL_COLOR = {
    "DEBUG":    "\033[38;5;245m",  # grey
    "INFO":     "\033[38;5;39m",   # blue
    "WARNING":  "\033[38;5;214m",  # amber
    "ERROR":    "\033[38;5;203m",  # red
    "CRITICAL": "\033[1;38;5;201m",# magenta bold
}
_RESET = "\033[0m"


class _ComponentFilter(logging.Filter):
    """Adds `component` = logger name without the shared 'bizassist.' prefix."""
    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name
        if name.startswith("bizassist."):
            name = name[len("bizassist."):]
        elif name == "bizassist":
            name = "app"
        record.component = name
        return True


class _Formatter(logging.Formatter):
    def __init__(self, use_color: bool):
        super().__init__(
            fmt="%(asctime)s %(levelname)-5s %(component)-22s %(message)s",
            datefmt="%H:%M:%S",
        )
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        # 5-char level: WARNING -> WARN, CRITICAL -> CRIT
        short = {"WARNING": "WARN", "CRITICAL": "CRIT"}.get(record.levelname, record.levelname)
        original = record.levelname
        record.levelname = short
        out = super().format(record)
        record.levelname = original
        if self.use_color:
            color = _LEVEL_COLOR.get(original)
            if color:
                out = f"{color}{out}{_RESET}"
        return out


def configure_logging(level: str = None, *, color: bool = None) -> None:
    """
    Install a single clean handler on the root logger. Idempotent.

    level: overrides LOG_LEVEL env (default INFO).
    color: force colour on/off; default = auto (on when stderr is a TTY and
           NO_COLOR is unset).
    """
    level_name = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    level_value = getattr(logging, level_name, logging.INFO)

    if color is None:
        color = sys.stderr.isatty() and os.getenv("NO_COLOR") is None

    root = logging.getLogger()
    # Replace any pre-existing handlers (e.g. a stray basicConfig) so we own output.
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.addFilter(_ComponentFilter())
    handler.setFormatter(_Formatter(use_color=color))

    root.addHandler(handler)
    root.setLevel(level_value)

    # App logger inherits the root handler; make sure it isn't accidentally raised.
    logging.getLogger("bizassist").setLevel(level_value)

    # Hush the noisy libraries.
    for lib in _NOISY_LIBS:
        logging.getLogger(lib).setLevel(logging.WARNING)

    logging.getLogger("bizassist.logging").info(
        f"{TAG.ADMIN} Logging configured — level={level_name}, color={'on' if color else 'off'}"
    )


def get_logger(name: str) -> logging.Logger:
    """
    Return a namespaced logger. Pass __name__; the 'bizassist.' prefix is added
    if missing so every app logger shares one parent and one config.
    """
    if name in ("__main__", None, ""):
        name = "app"
    if not name.startswith("bizassist"):
        name = f"bizassist.{name}"
    return logging.getLogger(name)
