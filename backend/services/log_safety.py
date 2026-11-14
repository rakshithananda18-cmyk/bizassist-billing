"""Keep untrusted diagnostic values on one physical log line."""


def log_value(value) -> str:
    """Escape record separators and terminal controls, preserving readable data."""
    return (str(value).replace("\r", "\\r").replace("\n", "\\n")
            .replace("\x1b", "\\x1b").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
