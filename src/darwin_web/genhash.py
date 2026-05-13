"""Random tokens for planner ``fill`` actions (username / password)."""

from __future__ import annotations

import re
import secrets
import string
from typing import Any

_FILL_USERNAME = "$GENHASH"
_FILL_PASSWORD = "$GENHASH_PW"
# Model typos like ``$GENHASH2`` or ``$GENHASH2@gmail.com`` — same intent as ``$GENHASH``.
_LOCAL_GENHASH_PATTERN = re.compile(r"^\$genhash\d*$", re.IGNORECASE)

_UNAME_ALPHABET = string.ascii_lowercase + string.digits
_PW_ALPHABET = string.ascii_letters + string.digits + "!@%^_+-="

_pw_cache: str | None = None

_PERSONAL_NAME_MARKERS = frozenset(
    {
        "firstname",
        "lastname",
        "first_name",
        "last_name",
        "givenname",
        "familyname",
        "middlename",
    }
)


def _is_personal_name_field(dom: dict[str, Any]) -> bool:
    """Google and similar flows use ``firstName`` / ``lastName`` — not username slots."""
    nm = str(dom.get("name", "")).strip().lower()
    if nm in _PERSONAL_NAME_MARKERS:
        return True
    aria = str(dom.get("aria_label", "")).strip().lower()
    return "first name" in aria or "last name" in aria


def reset_pw_cache() -> None:
    """Forget the last expanded ``$GENHASH_PW`` (new goal, navigation, or username step)."""
    global _pw_cache
    _pw_cache = None


def genhash(n: int = 18, *, password: bool = False) -> str:
    """Cryptographically random string for automated signup fields.

    * ``password=False``: lowercase letters and digits (fits many username / local-part rules).
    * ``password=True``: mixed case, digits, and a small punctuation set for typical password rules.
    """
    length = max(8, min(int(n), 128))
    alphabet = _PW_ALPHABET if password else _UNAME_ALPHABET
    return "".join(secrets.choice(alphabet) for _ in range(length))


def try_expand_fill(value: str, *, dom: dict[str, Any] | None = None) -> tuple[str, str | None]:
    """Expand ``$GENHASH`` / ``$GENHASH_PW`` when appropriate.

    Also accepts ``$GENHASH`` + optional digits (e.g. ``$GENHASH2``) and ``$GENHASH2@gmail.com``-style locals.

    Returns ``(expanded_value, error_message)``. *error_message* is set when a sentinel is used on
    the wrong field (e.g. legal name inputs); the executor should surface it to the planner.
    """
    global _pw_cache
    key = value.strip()

    if key == _FILL_PASSWORD:
        if dom is not None and _is_personal_name_field(dom):
            return (
                value,
                'fill: "$GENHASH_PW" is only for password fields, not First or Last name.',
            )
        if _pw_cache is None:
            _pw_cache = genhash(24, password=True)
        return _pw_cache, None

    def _expand_username_sentinel() -> tuple[str, str | None] | None:
        """Return expanded string or error tuple; None if this path does not apply."""
        if "@" in key:
            local, _, mail_host = key.partition("@")
            local = local.strip()
            if not _LOCAL_GENHASH_PATTERN.match(local):
                return None
        elif _LOCAL_GENHASH_PATTERN.match(key):
            mail_host = None
        else:
            return None
        if dom is not None and _is_personal_name_field(dom):
            return (
                value,
                'fill: "$GENHASH" is only for username or email-local-part fields, not First or Last '
                "name; use realistic given and family names (e.g. Alex, Rivera).",
            )
        reset_pw_cache()
        if mail_host is None:
            return genhash(18), None
        return f"{genhash(18)}@{mail_host}", None

    username_out = _expand_username_sentinel()
    if username_out is not None:
        return username_out

    return value, None


def expand_fill_value(value: str) -> str:
    """Replace planner sentinels (no DOM guard — for tests and callers without field context)."""
    out, err = try_expand_fill(value, dom=None)
    if err:
        raise RuntimeError(err)
    return out
