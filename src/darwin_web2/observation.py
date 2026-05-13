"""Structured page observation (DOM list + alerts + fingerprint). Language-neutral."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Page

from darwin_web.snapshot import page_alert_digest, page_snapshot, safe_page_url, snapshot_items_yaml


def nav_breadcrumb(url: str) -> str:
    """Host + path without query — stable across noisy query tokens."""
    try:
        p = urlparse(url)
        return f"{p.netloc}{p.path}".lower()
    except Exception:  # noqa: BLE001
        return (url or "")[:160].lower()


def observation_fingerprint(*, url: str, items: list[dict[str, Any]]) -> str:
    """Compact hash of visible interactive list (for stagnation detection)."""
    nb = nav_breadcrumb(url)
    slim: list[tuple[Any, ...]] = []
    for it in items[:48]:
        slim.append(
            (
                it.get("ref"),
                str(it.get("tag", "")).lower(),
                str(it.get("role", "")).lower(),
                str(it.get("text", ""))[:48],
                str(it.get("value", ""))[:32],
            )
        )
    raw = json.dumps({"u": nb, "n": len(items), "i": slim}, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class Observation:
    """One observe pass before/after an action."""

    url: str
    title: str
    items: list[dict[str, Any]]
    alert_digest: str
    fingerprint: str
    element_count: int

    def to_prompt_block(self) -> str:
        header = f"URL: {self.url}\nTitle: {self.title}\nObservation fingerprint: {self.fingerprint}\n"
        body = "Interactive elements (YAML; use ref in actions):\n" + snapshot_items_yaml(self.items)
        footer = (
            "\n---\nRules:\n"
            "- Use ``ref`` from the YAML for click/fill/scroll/select; ``pick_option`` targets a visible list row by its text.\n"
            "- Do not re-fill an input with the same text it already shows in ``value``.\n"
            "- When a screenshot is present, treat it as ground truth for overlays, open menus, and what blocks the goal; "
            "the YAML list can include controls hidden behind overlays.\n"
            "- ``select_option`` is only for native HTML ``<select>``; custom dropdowns are ``click`` + ``pick_option`` on "
            "a concrete row label, not the collapsed field label.\n"
            "- If a ``role=combobox`` element shows ``aria_expanded: 'true'``, the dropdown is already open. "
            "Do NOT click the combobox ref again (it would close it). Use ``pick_option`` with the desired option text, "
            "or ``click`` the specific ``role=option`` ref shown in the list.\n"
        )
        if self.alert_digest:
            header += f"\nVisible page alerts/errors (DOM):\n{self.alert_digest}\n"
        return header + body + footer


def gather_observation(page: Page) -> Observation:
    items, url = page_snapshot(page)
    digest = ""
    try:
        digest = page_alert_digest(page)
    except Exception:  # noqa: BLE001
        digest = ""
    title = ""
    try:
        title = page.title()
    except Exception:  # noqa: BLE001
        title = ""
    fp = observation_fingerprint(url=url or safe_page_url(page), items=items)
    return Observation(
        url=url or safe_page_url(page),
        title=title,
        items=items,
        alert_digest=digest.strip(),
        fingerprint=fp,
        element_count=len(items),
    )
