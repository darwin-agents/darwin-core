from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml

from playwright._impl._errors import TargetClosedError

if TYPE_CHECKING:
    from playwright.sync_api import Page


class PageClosed(RuntimeError):
    """The Playwright page (or browser session) is no longer attached — common with remote CDP."""


def safe_page_url(page: Page) -> str:
    """Best-effort current URL; empty string if the page is gone."""
    try:
        if page.is_closed():
            return ""
        u = page.url
        return u if isinstance(u, str) else ""
    except (TargetClosedError, RuntimeError, OSError):
        return ""


_ALERT_DIGEST_JS = r"""() => {
  const seen = new Set();
  const parts = [];
  function add(el) {
    if (seen.has(el)) return;
    const st = window.getComputedStyle(el);
    if (st.visibility === "hidden" || st.display === "none") return;
    let t = "";
    try {
      t = (el.innerText || "").trim().replace(/\s+/g, " ");
    } catch (e) {
      return;
    }
    if (t.length < 4 || t.length > 280) return;
    seen.add(el);
    parts.push(t);
  }
  document.querySelectorAll('[role="alert"]').forEach(add);
  // Only assertive live regions: polite is used for benign status (e.g. footer language
  // comboboxes) and must not be surfaced as "page alerts" to the planner.
  document.querySelectorAll('[aria-live="assertive"]').forEach((el) => {
    if (parts.length >= 6) return;
    add(el);
  });
  return parts.slice(0, 5).join(" | ");
}"""


def page_alert_digest(page: Page, *, max_chars: int = 420) -> str:
    """Short visible validation / live-region text for the planner (does not depend on vision)."""
    try:
        if page.is_closed():
            return ""
        raw = page.evaluate(_ALERT_DIGEST_JS)
    except (TargetClosedError, RuntimeError, OSError):
        return ""
    except Exception:  # noqa: BLE001
        return ""
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    if not s:
        return ""
    if len(s) > max_chars:
        return s[: max_chars - 1] + "…"
    return s


_DEEP_CLEAR_REFS_JS = r"""() => {
  const attrName = "data-darwin-web-ref";
  function clearRefs(root) {
    root.querySelectorAll("[" + attrName + "]").forEach((n) => n.removeAttribute(attrName));
    root.querySelectorAll("*").forEach((el) => {
      if (el.shadowRoot) clearRefs(el.shadowRoot);
    });
  }
  clearRefs(document);
}"""


# Tag interactive candidates (including inside Shadow roots, e.g. Google c-wiz sign-up).
_SNAPSHOT_JS = r"""
(() => {
  const attrName = "data-darwin-web-ref";
  function clearRefs(root) {
    root.querySelectorAll("[" + attrName + "]").forEach((n) => n.removeAttribute(attrName));
    root.querySelectorAll("*").forEach((el) => {
      if (el.shadowRoot) clearRefs(el.shadowRoot);
    });
  }
  clearRefs(document);
  const sel =
    'button,a[href],input:not([type="hidden"]),select,textarea,' +
    '[role="button"],[role="link"],[role="menuitem"],[role="tab"],' +
    '[role="combobox"],[role="listbox"],[role="option"],' +
    '[aria-haspopup="listbox"],[aria-haspopup="menu"]';
  const seen = new Set();
  const acc = [];
  function collect(root) {
    for (const el of root.querySelectorAll(sel)) {
      if (seen.has(el)) continue;
      seen.add(el);
      acc.push(el);
    }
    root.querySelectorAll("*").forEach((el) => {
      if (el.shadowRoot) collect(el.shadowRoot);
    });
  }
  collect(document);
  const nodes = acc;
  const items = [];
  let idx = 0;
  const margin = 120;
  for (const el of nodes) {
    const rect = el.getBoundingClientRect();
    const st = window.getComputedStyle(el);
    if (rect.width < 1 || rect.height < 1) continue;
    if (st.visibility === "hidden" || st.display === "none" || st.pointerEvents === "none")
      continue;
    if (rect.bottom < -margin || rect.top > innerHeight + margin) continue;
    idx += 1;
    el.setAttribute(attrName, String(idx));
    const tag = el.tagName.toLowerCase();
    const type = el.getAttribute("type") || "";
    const name = el.getAttribute("name") || "";
    const id = el.id || "";
    const href = el.getAttribute("href") || "";
    const role = el.getAttribute("role") || "";
    const aria = el.getAttribute("aria-label") || "";
    const placeholder = el.getAttribute("placeholder") || "";
    let text = "";
    try {
      text = (el.innerText || "").trim().replace(/\s+/g, " ").slice(0, 120);
    } catch (e) {
      text = "";
    }
    const ariaExpanded = el.getAttribute("aria-expanded") || "";
    const ariaHaspopup = el.getAttribute("aria-haspopup") || "";
    const value = "value" in el ? String(el.value || "").slice(0, 80) : "";
    items.push({
      ref: idx,
      tag,
      type,
      name,
      id,
      href: href.slice(0, 200),
      role,
      aria: aria.slice(0, 120),
      placeholder: placeholder.slice(0, 80),
      text,
      value,
      aria_expanded: ariaExpanded,
      aria_haspopup: ariaHaspopup,
    });
  }
  return items;
})()
"""


def clear_refs(page: Page) -> None:
    try:
        if page.is_closed():
            raise PageClosed("Cannot snapshot: page is already closed.")
        page.evaluate(_DEEP_CLEAR_REFS_JS)
    except TargetClosedError as exc:
        raise PageClosed(
            "Browser page, context, or CDP session was closed (remote tab ended or disconnected)."
        ) from exc


def page_snapshot(page: Page, *, max_items: int = 128) -> tuple[list[dict[str, Any]], str]:
    """Return (element descriptors, page url). Clears stale refs before tagging."""
    try:
        # Single-page apps often update the URL before the DOM list catches up; a short settle
        # reduces mismatches between ``URL:`` and the interactive element list.
        try:
            page.wait_for_timeout(250)
        except Exception:  # noqa: BLE001
            pass
        clear_refs(page)
        raw = page.evaluate(_SNAPSHOT_JS)
        url = safe_page_url(page)
    except TargetClosedError as exc:
        raise PageClosed(
            "Browser page, context, or CDP session was closed (remote tab ended or disconnected)."
        ) from exc
    if not isinstance(raw, list):
        return [], url
    items: list[dict[str, Any]] = []
    for entry in raw[:max_items]:
        if isinstance(entry, dict):
            items.append(entry)
    return items, url


def snapshot_items_yaml(items: list[dict[str, Any]]) -> str:
    """Compact YAML for the element list (token-efficient vs JSON)."""
    return yaml.safe_dump(
        items,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=160,
    ).rstrip()


def snapshot_prompt_block(items: list[dict[str, Any]], url: str, title: str) -> str:
    header = f"URL: {url}\nTitle: {title}\nInteractive elements (use ref in actions):\n"
    body = snapshot_items_yaml(items)
    footer = (
        "\n---\nNavigation hints:\n"
        "- The block above is a YAML list of interactive elements (refs are integers).\n"
        '- Each input includes a "value" field = current text in the DOM. If that already matches what you would type, '
        "do NOT use fill on that ref again.\n"
        "- When inputs look filled enough for this screen, advance: use click on the primary Next / Continue / "
        "Submit button (often tag=button with visible text like Next).\n"
        "- Multi-page flows: do not repeat the same fill on the same ref when the URL never changes.\n"
        "- Native <select>: use select_option (or fill). Custom combobox / listbox: click to open if closed; when "
        'role=option rows appear (or the list is open), use pick_option with {"op":"pick_option","label":"<visible text>"} '
        "or click the option ref. Avoid re-clicking the combobox trigger while the menu is open.\n"
        "- If the URL line and the listed controls look inconsistent (URL suggests a new step but controls match an older "
        "screen), trust the **screenshot** as ground truth; you may use wait_ms once for the UI to settle, then act on what "
        "is visible.\n"
        "- If a **Visible page alerts/errors** line appears below, treat it as authoritative for validation state (wrong code, "
        "taken username, etc.).\n"
        "- **Email/SMS verification codes** are not available to you from the browser session: do not invent codes; use "
        "**request_human** when a real code is required, or change strategy (Back / different email path).\n"
    )
    return header + body + footer
