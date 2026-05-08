from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import Page


def page_snapshot(page: Page) -> dict[str, Any]:
    url = page.url
    title = page.title()
    try:
        body_text = page.locator("body").inner_text(timeout=5000)
    except Exception:  # noqa: BLE001
        body_text = ""
    interactive_controls = page.evaluate(
        """() => {
            const nodes = Array.from(document.querySelectorAll('input, select, textarea, button, [role="button"], [role="combobox"], [role="listbox"]'));
            return nodes.slice(0, 80).map((el) => ({
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type'),
                name: el.getAttribute('name'),
                id: el.getAttribute('id'),
                role: el.getAttribute('role'),
                ariaLabel: el.getAttribute('aria-label'),
                placeholder: el.getAttribute('placeholder'),
                text: (el.textContent || '').trim().slice(0, 80),
                value: el.value ?? null,
                selectorHint: el.id ? `#${el.id}` : (el.getAttribute('name') ? `${el.tagName.toLowerCase()}[name="${el.getAttribute('name')}"]` : null),
            }));
        }"""
    )
    form_controls = page.evaluate(
        """() => {
            const nodes = Array.from(document.querySelectorAll('input, select, textarea, [role="combobox"]'));
            const comboboxNodes = Array.from(document.querySelectorAll('[role="combobox"]'));
            const byLabel = (el) => {
                const aria = el.getAttribute('aria-label');
                if (aria) return aria.trim();
                const id = el.getAttribute('id');
                if (id) {
                    const label = document.querySelector(`label[for="${id}"]`);
                    if (label && label.textContent) return label.textContent.trim();
                }
                const parentLabel = el.closest('label');
                if (parentLabel && parentLabel.textContent) return parentLabel.textContent.trim();
                return '';
            };
            return nodes.slice(0, 120).map((el) => {
                const tag = el.tagName.toLowerCase();
                const role = el.getAttribute('role');
                const style = window.getComputedStyle(el);
                const visible = style.display !== 'none' && style.visibility !== 'hidden';
                const rect = el.getBoundingClientRect();
                const options = tag === 'select'
                    ? Array.from(el.options || []).map((opt) => ({ value: opt.value, text: (opt.textContent || '').trim() }))
                    : [];
                let selectorHint = null;
                if (el.id) {
                    selectorHint = `#${el.id}`;
                } else if (el.getAttribute('name')) {
                    selectorHint = `${tag}[name="${el.getAttribute('name')}"]`;
                } else if (role === 'combobox') {
                    const idx = comboboxNodes.indexOf(el);
                    if (idx >= 0) selectorHint = `[role="combobox"]:nth-of-type(${idx + 1})`;
                }
                return {
                    tag,
                    role,
                    type: el.getAttribute('type'),
                    name: el.getAttribute('name'),
                    id: el.getAttribute('id'),
                    required: el.hasAttribute('required') || el.getAttribute('aria-required') === 'true',
                    disabled: el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true',
                    visible: visible && rect.width > 0 && rect.height > 0,
                    placeholder: el.getAttribute('placeholder'),
                    ariaLabel: el.getAttribute('aria-label'),
                    labelText: byLabel(el),
                    value: el.value ?? null,
                    text: (el.textContent || '').trim().slice(0, 120),
                    options,
                    selectorHint,
                };
            });
        }"""
    )
    return {
        "url": url,
        "title": title,
        "body_text_excerpt": body_text[:3000],
        "interactive_controls": interactive_controls,
        "form_controls": form_controls,
    }


def snapshot_signature(snapshot: dict[str, Any]) -> str:
    body_excerpt = str(snapshot.get("body_text_excerpt", ""))[:240]
    body_excerpt = re.sub(r"\s+", " ", body_excerpt).strip().lower()
    return "|".join([str(snapshot.get("url", "")), str(snapshot.get("title", "")), body_excerpt])

