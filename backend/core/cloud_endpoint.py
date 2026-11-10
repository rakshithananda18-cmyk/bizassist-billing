"""One cloud endpoint for desktop services and command-line tools."""
import logging
import os
from urllib.parse import urlsplit

DEFAULT_CLOUD_URL = "https://staterbill-api-1076771386585.asia-south1.run.app"
_VARIABLES = ("CLOUD_API_URL", "VITE_API_URL", "CLOUD_URL", "BIZASSIST_CLOUD_URL")
logger = logging.getLogger("bizassist.cloud")
_warned_retired = set()


def resolve_cloud_url(environ=None):
    environ = os.environ if environ is None else environ
    for name in _VARIABLES:
        value = (environ.get(name) or "").strip().rstrip("/")
        if not value:
            continue
        try:
            parsed = urlsplit(value)
            valid = (parsed.scheme in ("http", "https") and parsed.hostname
                     and not parsed.username and not parsed.password
                     and not parsed.query and not parsed.fragment
                     and not any(c.isspace() for c in value))
            parsed.port  # reject malformed ports
        except ValueError:
            valid = False
        if not valid:
            logger.warning("Ignoring invalid cloud URL in %s", name)
            continue
        if parsed.hostname.endswith(".hf.space") and value not in _warned_retired:
            logger.warning("%s selects the retired Hugging Face Space; use the Cloud Run endpoint", name)
            _warned_retired.add(value)
        return value, name
    return DEFAULT_CLOUD_URL, "default"


CLOUD_URL, CLOUD_URL_SOURCE = resolve_cloud_url()
