from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import ElementHandle

# Best-effort CSS path from a DOM node (prefers #id when present).
_JS_CSS_PATH = r"""(el) => {
  if (!(el instanceof Element)) return "";
  if (el.id) return "#" + CSS.escape(el.id);
  const parts = [];
  let node = el;
  while (node && node.nodeType === 1 && parts.length < 10) {
    let seg = node.tagName.toLowerCase();
    const parent = node.parentElement;
    if (parent) {
      const siblings = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
      if (siblings.length > 1) {
        const ix = siblings.indexOf(node) + 1;
        seg += ":nth-of-type(" + ix + ")";
      }
    }
    parts.unshift(seg);
    if (!parent) break;
    node = parent;
  }
  return parts.join(" > ");
}"""


def css_path_for_element(handle: ElementHandle) -> str:
    """Return a compact CSS path for *handle* (best-effort, no ephemeral data attrs)."""
    sel = handle.evaluate(_JS_CSS_PATH)
    return sel if isinstance(sel, str) and sel.strip() else "body"
