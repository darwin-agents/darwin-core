"""Richer page extraction for planner prompts and ``*-dom-input.yaml`` debug artifacts."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from playwright._impl._errors import TargetClosedError

if TYPE_CHECKING:
    from playwright.sync_api import Page


_FORM_HTML_JS = r"""() => {
  const candidates = [
    document.querySelector('[role="dialog"]'),
    document.querySelector("main"),
    document.querySelector('[role="main"]'),
    document.querySelector("form"),
    document.querySelector("#root"),
    document.body,
  ].filter(Boolean);
  const root = candidates[0];
  if (!root) return "";
  const clone = root.cloneNode(true);
  clone.querySelectorAll("script,style,noscript,svg,path,iframe").forEach((n) => n.remove());
  let html = "";
  try {
    html = clone.innerHTML || "";
  } catch (e) {
    html = "";
  }
  return html.replace(/\s+/g, " ").trim();
}"""


def _max_chars(env_key: str, default: int) -> int:
    raw = os.getenv(env_key, str(default)).strip()
    try:
        return max(0, min(int(raw, 10), 100_000))
    except ValueError:
        return default


def page_aria_snapshot(page: Page) -> str:
    """Playwright accessibility tree (YAML-like text). Empty string if unavailable."""
    cap = _max_chars("DARWIN_WEB2_ARIA_SNAPSHOT_MAX_CHARS", 16_000)
    try:
        raw = page.locator("body").aria_snapshot()
    except (TargetClosedError, RuntimeError, OSError):
        return ""
    except Exception:  # noqa: BLE001
        return ""
    if not isinstance(raw, str):
        return ""
    text = raw.strip()
    if cap > 0 and len(text) > cap:
        return text[: cap - 1] + "…"
    return text


def page_form_html_snippet(page: Page) -> str:
    """HTML inside main/form/dialog (scripts/styles stripped), for debugging custom widgets."""
    cap = _max_chars("DARWIN_WEB2_FORM_HTML_MAX_CHARS", 12_000)
    try:
        raw = page.evaluate(_FORM_HTML_JS)
    except (TargetClosedError, RuntimeError, OSError):
        return ""
    except Exception:  # noqa: BLE001
        return ""
    if not isinstance(raw, str):
        return ""
    text = raw.strip()
    if cap > 0 and len(text) > cap:
        return text[: cap - 1] + "…"
    return text


def snapshot_prompt_item_limit() -> int:
    return _max_chars("DARWIN_WEB2_SNAPSHOT_PROMPT_ITEMS", 128) or 128


def snapshot_artifact_item_limit() -> int:
    return _max_chars("DARWIN_WEB2_SNAPSHOT_ARTIFACT_ITEMS", 512) or 512
