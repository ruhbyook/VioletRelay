from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


_CREDENTIAL_RE = re.compile(
    r"(?i)(authorization|bearer|credentials?|password|pin|private[_ -]?key|secrets?|tokens?)"
    r"(\s*[:=]\s*)([^\s,}\]]+)"
)
_URL_RE = re.compile(r"https?://[^\s'\"]+")


def redact_text(value: str) -> str:
    value = _CREDENTIAL_RE.sub(r"\1\2<redacted>", value)

    def clean_url(match: re.Match[str]) -> str:
        raw = match.group(0)
        try:
            parts = urlsplit(raw)
            netloc = parts.netloc
            if parts.username is not None or parts.password is not None:
                host = parts.hostname or ""
                if ":" in host:
                    host = f"[{host}]"
                netloc = f"<redacted>@{host}"
                if parts.port is not None:
                    netloc += f":{parts.port}"
            return urlunsplit(
                (
                    parts.scheme,
                    netloc,
                    parts.path,
                    "<redacted>" if parts.query else "",
                    "",
                )
            )
        except ValueError:
            return "<invalid-url>"

    return _URL_RE.sub(clean_url, value)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def configure_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("reelferry")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    handler = RotatingFileHandler(log_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    return logger
