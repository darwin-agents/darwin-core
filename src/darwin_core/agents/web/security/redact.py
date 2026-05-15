"""Redact secrets before writing planner artifacts (YAML / prompts on disk)."""

from __future__ import annotations

import copy
import re
from typing import Any

_REDACTED = "***REDACTED***"
_GENHASH_PW_RE = re.compile(r"\$genhash_pw", re.IGNORECASE)
# Expanded password-like strings from genhash (mixed case + punctuation set).
_PW_LIKE_RE = re.compile(r"^[A-Za-z0-9!@%^_+\-=]{12,128}$")


def _looks_like_expanded_password(value: str) -> bool:
    s = value.strip()
    if len(s) < 12:
        return False
    if _GENHASH_PW_RE.search(s):
        return True
    if not _PW_LIKE_RE.match(s):
        return False
    has_upper = any(c.isupper() for c in s)
    has_lower = any(c.islower() for c in s)
    has_digit = any(c.isdigit() for c in s)
    has_sym = any(c in "!@%^_+-=" for c in s)
    return has_upper and has_lower and has_digit and has_sym


def redact_secrets_text(text: str) -> str:
    """Mask ``$GENHASH_PW`` tokens and obvious expanded password strings in free text."""
    if not text:
        return text
    out = _GENHASH_PW_RE.sub(_REDACTED, text)
    # Standalone long tokens on their own line (common in YAML value fields).
    def _line_sub(m: re.Match[str]) -> str:
        chunk = m.group(0)
        if _looks_like_expanded_password(chunk):
            return _REDACTED
        return chunk

    return re.sub(r"(?m)^[A-Za-z0-9!@%^_+\-=]{12,128}$", _line_sub, out)


def _redact_interactive_item(it: dict[str, Any]) -> dict[str, Any]:
    out = dict(it)
    typ = str(out.get("type", "")).lower()
    if typ == "password":
        if out.get("value"):
            out["value"] = _REDACTED
        return out
    val = out.get("value")
    if isinstance(val, str) and val.strip():
        if _GENHASH_PW_RE.search(val) or _looks_like_expanded_password(val):
            out["value"] = _REDACTED
    return out


def redact_value(value: Any) -> Any:
    """Deep-copy redaction for nested dict/list structures saved to artifacts."""
    if isinstance(value, str):
        return redact_secrets_text(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_value(v) for v in value)
    return value


def redact_dom_artifact(doc: dict[str, Any]) -> dict[str, Any]:
    """Redact interactive element list inside a dom-input artifact payload."""
    out = copy.deepcopy(doc)
    items = out.get("interactive_elements")
    if isinstance(items, list):
        out["interactive_elements"] = [
            _redact_interactive_item(it) if isinstance(it, dict) else it for it in items
        ]
    return redact_value(out)


def redact_turn_artifact_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Redact an ``*-llm-turn-v2.yaml`` document before write."""
    return redact_value(doc)
