from __future__ import annotations

from reelferry.logging_utils import redact_text


def error_message(error: BaseException, fallback: str) -> str:
    """Return a non-empty user-facing error without losing useful context."""
    message = str(error).strip()
    return redact_text(message or fallback)
