"""
app/logging_config.py — one place to configure logging for BizAssist Task.

Same format and switches as billing's backend/logging_config.py, so a line from
either service reads the same and greps the same:

    12:34:56 INFO  task.auth              [BizId=BA-JABXGD] [AUTH] staff login biz=7 staff=3
    12:34:56 WARN  task                   [BizId=-] [TRACK] ping purge failed

* COMPONENT column = logger name without the shared "bizassist." prefix.
* [BizId=…] = the caller's BizID, set per request by the HTTP middleware in
  main.py ("-" for system lines and unauthenticated requests).
* [TAG] inside the message marks the sub-system (see TAG).
* LOG_LEVEL (default INFO), LOG_FILE=path (rotating, plain text; opt-in),
  LOG_FORMAT=json (ECS-style, service.name "bizassist-task"), NO_COLOR.

Usage
-----
    from app.logging_config import get_logger, TAG
    logger = get_logger("task.auth")              # -> "bizassist.task.auth"
    logger.info("%s owner login biz=%s", TAG.AUTH, user.id)
"""
import contextvars
import json
import logging
import os
import sys
from datetime import datetime, timezone

# Request-scoped BizID (owner's public_id, e.g. "BA-JABXGD"). Set in the async
# HTTP middleware (main.py), NOT in a sync dependency: a sync dependency runs in
# a threadpool context that is discarded before the route handler logs.
current_bizid_var = contextvars.ContextVar("current_bizid", default=None)


class TAG:
    BOOT  = "[BOOT]"    # startup, migrations
    AUTH  = "[AUTH]"    # owner / staff sign-in, SSO from billing, device policy
    FIELD = "[FIELD]"   # attendance, runs, tasks, requests
    TRACK = "[TRACK]"   # location pings, purge loop
    HTTP  = "[HTTP]"    # unhandled request errors


# Third-party loggers that spam INFO/DEBUG — keep them at WARNING.
_NOISY_LIBS = ("httpx", "httpcore", "urllib3", "asyncio", "watchfiles", "uvicorn.access",
               "multipart", "python_multipart")

_LEVEL_COLOR = {
    "DEBUG":    "\033[38;5;245m",
    "INFO":     "\033[38;5;39m",
    "WARNING":  "\033[38;5;214m",
    "ERROR":    "\033[38;5;203m",
    "CRITICAL": "\033[1;38;5;201m",
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


class _BizIdFilter(logging.Filter):
    """Stamps `biz_id` on every record. Never raises."""
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.biz_id = current_bizid_var.get() or "-"
        except Exception:
            record.biz_id = "-"
        return True


class _Formatter(logging.Formatter):
    def __init__(self, use_color: bool):
        super().__init__(
            fmt="%(asctime)s %(levelname)-5s %(component)-22s [BizId=%(biz_id)s] %(message)s",
            datefmt="%H:%M:%S",
        )
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "biz_id"):
            record.biz_id = "-"
        if not hasattr(record, "component"):
            record.component = record.name
        short = {"WARNING": "WARN", "CRITICAL": "CRIT"}.get(record.levelname, record.levelname)
        original = record.levelname
        record.levelname = short
        out = super().format(record)
        record.levelname = original
        if self.use_color and original in _LEVEL_COLOR:
            out = f"{_LEVEL_COLOR[original]}{out}{_RESET}"
        return out


class _JsonFormatter(logging.Formatter):
    """ECS-aligned structured logs (LOG_FORMAT=json). Never logs secrets."""
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "biz_id"):
            record.biz_id = "-"
        if not hasattr(record, "component"):
            record.component = record.name
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") \
            + f"{int(record.msecs):03d}Z"
        payload = {
            "@timestamp": ts,
            "log.level": record.levelname.lower(),
            "biz_id": record.biz_id,
            "service.name": "bizassist-task",
            "component": record.component,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["error.stack_trace"] = self.formatException(record.exc_info)
        labels = getattr(record, "labels", None)
        if isinstance(labels, dict):
            payload["labels"] = labels
        return json.dumps(payload, ensure_ascii=False)


def _make_formatter(use_color: bool) -> logging.Formatter:
    if (os.getenv("LOG_FORMAT") or "").lower() == "json":
        return _JsonFormatter()
    return _Formatter(use_color=use_color)


def _handler(handler: logging.Handler, use_color: bool) -> logging.Handler:
    handler.addFilter(_ComponentFilter())
    handler.addFilter(_BizIdFilter())
    handler.setFormatter(_make_formatter(use_color))
    return handler


def configure_logging(level: str = None, *, color: bool = None) -> None:
    """Install one clean handler on the root logger (plus LOG_FILE). Idempotent."""
    level_name = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    level_value = getattr(logging, level_name, logging.INFO)
    if color is None:
        color = sys.stderr.isatty() and os.getenv("NO_COLOR") is None

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(_handler(logging.StreamHandler(stream=sys.stderr), color))

    log_file = os.getenv("LOG_FILE")
    if log_file:
        try:
            from logging.handlers import RotatingFileHandler

            class _SafeRotatingFileHandler(RotatingFileHandler):
                def doRollover(self):
                    try:
                        super().doRollover()
                    except PermissionError:
                        # Windows: the uvicorn --reload parent still holds the
                        # file; keep writing to the current one.
                        pass

            os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
            root.addHandler(_handler(
                _SafeRotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"), False))
        except Exception as e:
            logging.getLogger("bizassist.logging").warning("%s file log disabled: %s", TAG.BOOT, e)

    root.setLevel(level_value)
    logging.getLogger("bizassist").setLevel(level_value)
    for lib in _NOISY_LIBS:
        logging.getLogger(lib).setLevel(logging.WARNING)

    logging.getLogger("bizassist.logging").info(
        "%s Logging configured — level=%s, color=%s, file=%s",
        TAG.BOOT, level_name, "on" if color else "off", log_file or "off")


def get_logger(name: str) -> logging.Logger:
    """A namespaced logger: 'task.auth' -> 'bizassist.task.auth'."""
    if name in ("__main__", None, ""):
        name = "task"
    if not name.startswith("bizassist"):
        name = f"bizassist.{name}"
    return logging.getLogger(name)
