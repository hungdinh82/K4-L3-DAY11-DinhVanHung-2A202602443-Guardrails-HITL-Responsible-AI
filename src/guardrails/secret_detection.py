"""Canonical detection of demo secrets hidden through simple transformations."""
from __future__ import annotations

import re
import unicodedata

from core.config import DEMO_SECRETS


def _compact(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"[^a-z0-9]", "", normalized)


def decode_decimal_codepoints(text: str) -> str:
    """Decode decimal Unicode rows so encoded demo secrets remain detectable."""
    values = re.findall(r"(?<![\w.])\d{2,6}(?![\w.])", text or "")
    if len(values) < 4:
        return ""
    try:
        return "".join(chr(int(value)) for value in values if int(value) <= 0x10FFFF)
    except (ValueError, OverflowError):
        return ""


def contains_known_secret_variant(text: str) -> bool:
    """Catch direct, reversed, split-character, full-width and acrostic leaks."""
    raw = unicodedata.normalize("NFKC", text or "")
    folded = raw.casefold()
    compact = _compact(raw)

    spelled_parts = re.findall(
        r"(?<!\w)(?:[a-z0-9][\s-]){3,}[a-z0-9](?!\w)", folded
    )
    spelled = "".join(_compact(part) for part in spelled_parts)

    line_initials = _compact(
        "".join(line.strip()[:1] for line in raw.splitlines() if line.strip())
    )
    uppercase_initials = _compact(
        "".join(ch for ch in raw if ch.isupper() or ch.isdigit())
    )

    for secret in DEMO_SECRETS:
        normalized_secret = unicodedata.normalize("NFKC", secret).casefold()
        compact_secret = _compact(secret)
        if not compact_secret:
            continue
        if normalized_secret in folded or normalized_secret[::-1] in folded:
            return True
        if compact_secret in compact or compact_secret[::-1] in compact:
            return True
        if compact_secret in spelled or compact_secret[::-1] in spelled:
            return True
        if compact_secret in line_initials or compact_secret in uppercase_initials:
            return True
    return False
