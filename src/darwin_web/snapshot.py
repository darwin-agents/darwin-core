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
    )
    return header + body + footer
