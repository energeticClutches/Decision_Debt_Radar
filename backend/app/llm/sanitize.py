"""Untrusted customer text handling (docs/day-5-implementation-brief.md section 10).

Customer text is data, never instructions. Before it leaves the application it is (1) redacted (emails and phone-like digit runs,
basic redaction only, no PII pipeline), (2) escaped so that it cannot forge or close the wrapper tag, and (3) wrapped in
<untrusted_customer_text>. Only synthetic data is ever sent.
"""

from __future__ import annotations

import html
import re

TAG = "untrusted_customer_text"
MAX_TEXT_CHARS = 1000
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# a phone-like run: an optional +, then at least 7 digits that may be separated by spaces, dots, dashes or brackets
_PHONE = re.compile(r"(?<![\w.])\+?\(?\d(?:[\s().\-]?\d){6,}(?![\w])")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def redact(text: str) -> str:
    text = _EMAIL.sub("[redacted-email]", text)
    return _PHONE.sub("[redacted-phone]", text)


def escape(text: str) -> str:
    """Neutralise markup: < > & become entities, so the closing tag of the wrapper can never appear inside the text."""
    return html.escape(_CONTROL.sub("", text), quote=False)


def unescape(text: str) -> str:
    return html.unescape(text)


def wrap(text: str) -> str:
    """redact -> truncate -> escape -> wrap."""
    cleaned = redact(text)[:MAX_TEXT_CHARS]
    return f"<{TAG}>{escape(cleaned)}</{TAG}>"


def unwrap(wrapped: str) -> str:
    """Inverse of wrap for tests and the stub classifier: strip the wrapper and unescape."""
    body = wrapped
    if body.startswith(f"<{TAG}>") and body.endswith(f"</{TAG}>"):
        body = body[len(TAG) + 2: -(len(TAG) + 3)]
    return unescape(body)
