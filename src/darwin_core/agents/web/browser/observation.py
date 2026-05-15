"""Structured page observation (interactive list + a11y tree + form HTML snippet)."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Page

from darwin_core.agents.web.browser.dom_extract import (
    page_aria_snapshot,
    page_form_html_snippet,
    snapshot_artifact_item_limit,
    snapshot_prompt_item_limit,
)
from darwin_core.agents.web.browser.snapshot import (
    PageNavigating,
    page_alert_digest,
    page_snapshot,
    resolve_live_page,
    safe_page_url,
    snapshot_items_yaml,
)


def nav_breadcrumb(url: str) -> str:
    """Host + path without query — stable across noisy query tokens."""
    try:
        p = urlparse(url)
        return f"{p.netloc}{p.path}".lower()
    except Exception:  # noqa: BLE001
        return (url or "")[:160].lower()


_VOLATILE_INPUT_TYPES = frozenset({"", "text", "email", "search", "tel", "url", "password", "number"})


def _fingerprint_item_slot(it: dict[str, Any], *, ignore_volatile_values: bool) -> tuple[Any, ...]:
    """One interactive element slot for hashing; optionally drop typed user input."""
    tag = str(it.get("tag", "")).lower()
    typ = str(it.get("type", "")).lower()
    role = str(it.get("role", "")).lower()
    volatile = (
        ignore_volatile_values
        and tag in ("input", "textarea")
        and typ in _VOLATILE_INPUT_TYPES
    )
    text = "" if volatile else str(it.get("text", ""))[:48]
    value = "" if volatile else str(it.get("value", ""))[:32]
    checked = ""
    if typ in ("checkbox", "radio"):
        checked = str(it.get("checked", "")).lower()
    return (it.get("ref"), tag, role, typ, text, value, checked)


def observation_fingerprint(*, url: str, items: list[dict[str, Any]]) -> str:
    """Compact hash of visible interactive list (display + coarse change detection)."""
    return _observation_fingerprint_impl(url=url, items=items, ignore_volatile_values=False)


def observation_layout_fingerprint(*, url: str, items: list[dict[str, Any]]) -> str:
    """Layout hash ignoring text/email input values — for stagnation when only field text changes."""
    return _observation_fingerprint_impl(url=url, items=items, ignore_volatile_values=True)


def _observation_fingerprint_impl(
    *, url: str, items: list[dict[str, Any]], ignore_volatile_values: bool
) -> str:
    nb = nav_breadcrumb(url)
    slim = [_fingerprint_item_slot(it, ignore_volatile_values=ignore_volatile_values) for it in items[:48]]
    raw = json.dumps({"u": nb, "n": len(items), "i": slim}, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _include_aria_in_prompt() -> bool:
    v = os.getenv("DARWIN_WEB2_DOM_ARIA", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _include_form_html_in_prompt() -> bool:
    v = os.getenv("DARWIN_WEB2_DOM_FORM_HTML", "0").strip().lower()
    return v in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Observation:
    """One observe pass before/after an action."""

    url: str
    title: str
    items: list[dict[str, Any]]
    alert_digest: str
    fingerprint: str
    layout_fingerprint: str
    element_count: int
    aria_snapshot: str = ""
    form_html: str = ""
    prompt_item_limit: int = 128

    def prompt_items(self) -> list[dict[str, Any]]:
        return self.items[: self.prompt_item_limit]

    def to_dom_artifact(self) -> dict[str, Any]:
        """Full extraction payload for ``NNN-dom-input.yaml`` (debug; not truncated like the LLM prompt)."""
        return {
            "page_url": self.url,
            "title": self.title,
            "observation_fingerprint": self.fingerprint,
            "layout_fingerprint": self.layout_fingerprint,
            "visible_alerts": self.alert_digest or None,
            "extraction": {
                "interactive_element_count": self.element_count,
                "interactive_element_cap": snapshot_artifact_item_limit(),
                "prompt_interactive_limit": self.prompt_item_limit,
                "aria_snapshot_chars": len(self.aria_snapshot),
                "form_html_chars": len(self.form_html),
            },
            "aria_snapshot": self.aria_snapshot or None,
            "form_html": self.form_html or None,
            "interactive_elements": self.items,
        }

    def to_prompt_block(self) -> str:
        header = f"URL: {self.url}\nTitle: {self.title}\nObservation fingerprint: {self.fingerprint}\n"
        if self.alert_digest:
            header += f"\nVisible page alerts/errors (DOM):\n{self.alert_digest}\n"

        sections: list[str] = []

        if _include_aria_in_prompt() and self.aria_snapshot:
            sections.append(
                "Accessibility tree (YAML-like; use with interactive list and screenshot):\n"
                + self.aria_snapshot
            )

        if _include_form_html_in_prompt() and self.form_html:
            sections.append("Form region HTML (truncated; debugging structure):\n" + self.form_html)

        prompt_items = self.prompt_items()
        if len(self.items) > len(prompt_items):
            header += (
                f"\nInteractive elements shown: {len(prompt_items)} of {self.element_count} "
                f"(see dom-input artifact for full list).\n"
            )

        body = "Interactive elements (YAML; use ref in actions):\n" + snapshot_items_yaml(prompt_items)
        footer = (
            "\n---\nRules:\n"
            "- Use ``ref`` from the YAML for click/fill/scroll/select.\n"
            "- Custom ``role=combobox`` → prefer ``combobox_pick`` with ref + visible row label; "
            "``pick_option`` only when option rows are already in the list below.\n"
            "- Native ``<select>`` → ``select_option``.\n"
            "- Do not re-fill an input when ``value`` already matches.\n"
            "- When a screenshot is attached, treat it as ground truth for layout, open menus, and errors.\n"
        )
        mid = ("\n\n".join(sections) + "\n\n") if sections else ""
        return header + mid + body + footer


def gather_observation_resilient(page: Page) -> Observation:
    """Like :func:`gather_observation` but waits out a late navigation if the first pass races it."""
    try:
        return gather_observation(page)
    except PageNavigating:
        live = resolve_live_page(page)
        try:
            live.wait_for_load_state("domcontentloaded", timeout=12_000)
        except Exception:  # noqa: BLE001
            pass
        try:
            live.wait_for_timeout(400)
        except Exception:  # noqa: BLE001
            pass
        return gather_observation(resolve_live_page(live))


def gather_observation(page: Page) -> Observation:
    art_cap = snapshot_artifact_item_limit()
    prompt_cap = snapshot_prompt_item_limit()
    items, url = page_snapshot(page, max_items=art_cap)
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
    aria = page_aria_snapshot(page)
    form_html = page_form_html_snippet(page)
    safe_url = url or safe_page_url(page)
    fp = observation_fingerprint(url=safe_url, items=items)
    layout_fp = observation_layout_fingerprint(url=safe_url, items=items)
    return Observation(
        url=safe_url,
        title=title,
        items=items,
        alert_digest=digest.strip(),
        fingerprint=fp,
        layout_fingerprint=layout_fp,
        element_count=len(items),
        aria_snapshot=aria,
        form_html=form_html,
        prompt_item_limit=prompt_cap,
    )
