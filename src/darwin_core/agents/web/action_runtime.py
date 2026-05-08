from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .google_actions import try_google_click_next, try_google_gender_select, try_google_month_select
from .prompts import GENDER_OPTIONS, MONTH_NAMES

if TYPE_CHECKING:
    from playwright.sync_api import Page


def action_signature(action: dict[str, Any]) -> str:
    return "|".join(
        [
            str(action.get("action")),
            str(action.get("selector")),
            str(action.get("url")),
            str(action.get("text")),
            str(action.get("value")),
            str(action.get("key")),
            str(action.get("target_text")),
        ]
    )


def fallback_action(snapshot: dict[str, Any]) -> dict[str, Any]:
    url = str(snapshot.get("url", ""))
    title = str(snapshot.get("title", "")).lower()
    if "birthdaygender" in url or "basic information" in title:
        return {
            "action": "click",
            "selector": "[aria-label='Month'], [id*='month'], [name*='month']",
            "value": None,
            "key": None,
            "target_text": None,
            "text": None,
            "url": None,
            "wait_ms": None,
            "reason": "Fallback: focus month selector on birthday page.",
        }
    if "accounts.google.com" in url:
        return {
            "action": "click",
            "selector": "button:has-text('Next')",
            "value": None,
            "key": None,
            "target_text": None,
            "text": None,
            "url": None,
            "wait_ms": None,
            "reason": "Fallback: move forward in Google signup flow.",
        }
    return {
        "action": "wait",
        "selector": None,
        "value": None,
        "key": None,
        "target_text": None,
        "text": None,
        "url": None,
        "wait_ms": 1200,
        "reason": "Fallback: wait for page state to settle.",
    }


def run_action(page: Page, action: dict[str, Any]) -> bool:
    kind = action.get("action")
    selector = action.get("selector")
    text = action.get("text")
    value = action.get("value")
    key = action.get("key")
    target_text = action.get("target_text")
    url = action.get("url")
    wait_ms = action.get("wait_ms")

    if kind == "done":
        return False
    if kind == "goto":
        if not isinstance(url, str) or not url:
            raise RuntimeError("goto action missing url.")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return True
    if kind == "click":
        if not isinstance(selector, str) or not selector:
            raise RuntimeError("click action missing selector.")
        if selector == "button:has-text('Next')" and try_google_click_next(page):
            if isinstance(wait_ms, (int, float)) and wait_ms > 0:
                page.wait_for_timeout(int(wait_ms))
            return True
        page.locator(selector).first.click(timeout=10000)
        if isinstance(wait_ms, (int, float)) and wait_ms > 0:
            page.wait_for_timeout(int(wait_ms))
        selector_lower = selector.lower()
        month_click_selector = (
            "month" in selector_lower
            or "aria-label='month'" in selector_lower
            or 'aria-label="month"' in selector_lower
            or ":nth-of-type(1)" in selector_lower
        )
        gender_click_selector = (
            "gender" in selector_lower
            or "aria-label='gender'" in selector_lower
            or 'aria-label="gender"' in selector_lower
            or ":nth-of-type(2)" in selector_lower
        )
        if month_click_selector and try_google_month_select(page, "January"):
            return True
        if gender_click_selector and try_google_gender_select(page, "Male"):
            return True
        return True
    if kind == "type":
        if not isinstance(selector, str) or not selector:
            raise RuntimeError("type action missing selector.")
        text_value = text if isinstance(text, str) else value if isinstance(value, str) else None
        if not isinstance(text_value, str):
            raise RuntimeError("type action missing text/value.")
        page.locator(selector).first.fill(text_value, timeout=10000)
        return True
    if kind == "select_option":
        if not isinstance(selector, str) or not selector:
            raise RuntimeError("select_option action missing selector.")
        if not isinstance(value, str) or not value:
            raise RuntimeError("select_option action missing value.")
        locator = page.locator(selector).first
        try:
            locator.select_option(value=value, timeout=10000)
        except Exception:
            try:
                locator.select_option(label=value, timeout=10000)
            except Exception:
                locator.click(timeout=10000)
                page.wait_for_timeout(700)
                clicked = False
                for list_sel in ("li", "[role='option']", "[role='menuitem']"):
                    try:
                        candidate = page.locator(list_sel).filter(has_text=value).first
                        if candidate.is_visible(timeout=2000):
                            candidate.click(timeout=5000)
                            clicked = True
                            break
                    except Exception:  # noqa: BLE001
                        continue
                if not clicked:
                    page.get_by_text(value, exact=True).first.click(timeout=10000)
        return True
    if kind == "click_text":
        if not isinstance(target_text, str) or not target_text:
            raise RuntimeError("click_text action missing target_text.")
        if target_text in MONTH_NAMES and try_google_month_select(page, target_text):
            return True
        if target_text in GENDER_OPTIONS and try_google_gender_select(page, target_text):
            return True
        for list_sel in ("li", "[role='option']", "[role='menuitem']"):
            try:
                candidate = page.locator(list_sel).filter(has_text=target_text).first
                if candidate.is_visible(timeout=2000):
                    candidate.click(timeout=5000)
                    return True
            except Exception:  # noqa: BLE001
                continue
        try:
            page.get_by_text(target_text, exact=True).first.click(timeout=5000)
            return True
        except Exception:  # noqa: BLE001
            pass
        page.get_by_text(target_text, exact=False).first.click(timeout=10000)
        return True
    if kind == "press":
        if not isinstance(key, str) or not key:
            raise RuntimeError("press action missing key.")
        if isinstance(selector, str) and selector:
            page.locator(selector).first.press(key, timeout=10000)
        else:
            page.keyboard.press(key)
        return True
    if kind == "wait":
        timeout_ms = int(wait_ms) if isinstance(wait_ms, (int, float)) else 1000
        page.wait_for_timeout(max(100, timeout_ms))
        return True
    raise RuntimeError(f"Unknown action type: {kind}")

