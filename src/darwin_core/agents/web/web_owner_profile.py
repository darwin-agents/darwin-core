"""Human-owner profile for web automation (JSON on disk or :meth:`WebOwnerProfile.from_dict`).

Expected JSON keys (all non-empty strings): ``email``, ``password``, ``first_name``,
``last_name``, ``phone``, ``birth_day``, ``birth_month``, ``birth_year``, ``gender``.
Optional: ``generic_text`` for unknown text fields (defaults to ``first_name``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REQUIRED_STRING_FIELDS = (
    "email",
    "password",
    "first_name",
    "last_name",
    "phone",
    "birth_day",
    "birth_month",
    "birth_year",
    "gender",
)


@dataclass(frozen=True, slots=True)
class WebOwnerProfile:
    """Identity and demographics for the human owner; used for web form auto-fill."""

    email: str
    password: str
    first_name: str
    last_name: str
    phone: str
    birth_day: str
    birth_month: str
    birth_year: str
    gender: str
    generic_text: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebOwnerProfile:
        if not isinstance(data, dict):
            msg = f"owner profile must be a JSON object, got {type(data).__name__}"
            raise TypeError(msg)
        missing: list[str] = []
        for key in _REQUIRED_STRING_FIELDS:
            raw = data.get(key)
            if not isinstance(raw, str) or not raw.strip():
                missing.append(key)
        if missing:
            msg = "owner profile missing or empty required field(s): " + ", ".join(sorted(missing))
            raise ValueError(msg)
        generic = data.get("generic_text")
        if isinstance(generic, str) and generic.strip():
            generic_text = generic.strip()
        else:
            generic_text = str(data["first_name"]).strip()
        return cls(
            email=str(data["email"]).strip(),
            password=str(data["password"]).strip(),
            first_name=str(data["first_name"]).strip(),
            last_name=str(data["last_name"]).strip(),
            phone=str(data["phone"]).strip(),
            birth_day=str(data["birth_day"]).strip(),
            birth_month=str(data["birth_month"]).strip(),
            birth_year=str(data["birth_year"]).strip(),
            gender=str(data["gender"]).strip(),
            generic_text=generic_text,
        )


def load_web_owner_profile(path: str | Path) -> WebOwnerProfile:
    """Load :class:`WebOwnerProfile` from a JSON file (UTF-8)."""
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"owner profile file must contain a JSON object, got {type(raw).__name__}"
        raise TypeError(msg)
    return WebOwnerProfile.from_dict(raw)
