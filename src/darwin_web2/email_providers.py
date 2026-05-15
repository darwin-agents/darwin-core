"""Ranked email signup providers from ``config/emails.json`` (easiest → hardest)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class EmailProvider:
    provider: str
    country: str
    url: str
    bot_difficulty: str
    notes: str


# Goal text → canonical provider keys in emails.json (order preserved via file order).
_PROVIDER_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("mailfence", ("mailfence",)),
    ("inbox.lv", ("inbox.lv", "inbox lv")),
    ("mail.com", ("mail.com", "mail com")),
    ("gmx", ("gmx",)),
    ("mail.ru", ("mail.ru", "mailru", "mail ru")),
    ("proton", ("proton", "protonmail", "proton mail")),
    ("tuta", ("tuta", "tutanota")),
    ("zoho", ("zoho",)),
    ("yahoo", ("yahoo",)),
    ("outlook", ("outlook", "hotmail", "live.com", "microsoft", "signup.live")),
    ("gmail", ("gmail", "google mail")),
)


def default_emails_config_path() -> Path:
    raw = os.getenv(
        "DARWIN_WEB2_EMAILS_CONFIG",
        str(Path(__file__).resolve().parents[2] / "config" / "emails.json"),
    )
    return Path(raw)


def _clean_notes(text: str) -> str:
    return re.sub(r"\s*\[cite:\s*\d+\]\s*", " ", text).strip()


def load_email_providers(path: Path | None = None) -> list[EmailProvider]:
    """Load provider list; file order = easiest → hardest (do not re-sort)."""
    cfg = path if path is not None else default_emails_config_path()
    if not cfg.is_file():
        return []
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return []
    out: list[EmailProvider] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider", "")).strip()
        url = str(row.get("url", "")).strip()
        if not provider or not url:
            continue
        out.append(
            EmailProvider(
                provider=provider,
                country=str(row.get("country", "")).strip(),
                url=url,
                bot_difficulty=str(row.get("bot_difficulty", "")).strip(),
                notes=_clean_notes(str(row.get("notes", ""))),
            )
        )
    return out


def _provider_key(provider_name: str, url: str) -> str:
    blob = f"{provider_name} {url}".lower()
    for key, needles in _PROVIDER_KEYS:
        if any(n in blob for n in needles):
            return key
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host or provider_name.lower()


def goal_wants_email_creation(goal: str) -> bool:
    """True when the user likely wants a new mailbox signup flow."""
    g = goal.lower()
    if not g.strip():
        return False
    mailbox = any(
        w in g
        for w in (
            "email",
            "e-mail",
            "mail account",
            "mailbox",
            "inbox",
            "mail.com",
            "gmail",
            "outlook",
            "hotmail",
            "proton",
            "yahoo",
            "zoho",
            "mailfence",
            "sign up",
            "signup",
            "sign-up",
            "register",
            "create account",
            "open account",
        )
    )
    create = any(
        w in g
        for w in (
            "open",
            "create",
            "sign up",
            "signup",
            "register",
            "new account",
            "get a",
            "make a",
        )
    )
    return mailbox and create


def _excluded_keys_from_goal(goal: str) -> set[str]:
    g = goal.lower()
    excluded: set[str] = set()
    for key, needles in _PROVIDER_KEYS:
        for needle in needles:
            for pat in (
                f"not {needle}",
                f"not in {needle}",
                f"no {needle}",
                f"without {needle}",
                f"avoid {needle}",
                f"except {needle}",
            ):
                if pat in g:
                    excluded.add(key)
                    break
    return excluded


def _explicit_target_key(goal: str) -> str | None:
    """User named one provider positively (e.g. 'open gmail account')."""
    g = goal.lower()
    excluded = _excluded_keys_from_goal(goal)
    hits: list[str] = []
    for key, needles in _PROVIDER_KEYS:
        if key in excluded:
            continue
        for needle in needles:
            if needle in g:
                hits.append(key)
                break
    if len(hits) == 1:
        return hits[0]
    # Prefer longer / more specific match when multiple hit (e.g. proton mail vs mail)
    if len(hits) > 1:
        needles_by_key = dict(_PROVIDER_KEYS)
        ordered = sorted(
            hits,
            key=lambda k: -max((len(n) for n in needles_by_key[k] if n in g), default=0),
        )
        return ordered[0]
    return None


def select_providers_for_goal(
    goal: str,
    providers: list[EmailProvider],
) -> list[EmailProvider]:
    """Filter ranked list for this goal (exclusions + optional explicit provider)."""
    if not providers:
        return []
    excluded = _excluded_keys_from_goal(goal)
    explicit = _explicit_target_key(goal)

    keyed: list[tuple[str, EmailProvider]] = [
        (_provider_key(p.provider, p.url), p) for p in providers
    ]

    if explicit is not None:
        picked = [p for k, p in keyed if k == explicit]
        return picked if picked else list(providers)

    return [p for k, p in keyed if k not in excluded]


def build_email_providers_prompt_block(
    goal: str,
    providers: list[EmailProvider],
) -> str:
    """Planner context: which providers to try, in order."""
    if not goal_wants_email_creation(goal):
        return ""
    chosen = select_providers_for_goal(goal, providers)
    if not chosen:
        return ""

    lines = [
        "EMAIL_PROVIDER_RANKING (config/emails.json — easiest → hardest; follow this order):",
        "When the USER_GOAL is to create/open a new mailbox and does not name one provider, "
        "start with the first entry below (``goto`` its URL) unless you are already on that "
        "provider's signup flow.",
        "If signup is blocked (CAPTCHA loops, repeated 'try again', mandatory phone with no "
        "alternative, hard human wall), move to the **next** provider in this list (``goto`` "
        "its URL) — do not keep hammering the same site.",
        "Use OWNER_PROFILE for personal fields; ``$GENHASH`` only for **new** local parts on the "
        "provider you are signing up for.",
        "",
    ]
    for i, p in enumerate(chosen, start=1):
        line = f"  {i}. {p.provider} ({p.bot_difficulty}) — {p.url}"
        if p.notes:
            line += f" — {p.notes[:220]}"
        lines.append(line)

    first = chosen[0]
    lines.append("")
    lines.append(
        f"Preferred start: ``goto`` {first.url} if you are not already on {first.provider}'s signup."
    )
    return "\n".join(lines) + "\n"
