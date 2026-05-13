"""Execute planner JSON actions against a Playwright page.

This module bridges the LLM planner schema (``goto``, ``click``, ``type``, …)
to Playwright primitives. It adds targeted workarounds for Google account
signup flows (month/gender comboboxes, Next) via ``google_actions``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from .google_actions import try_google_click_next, try_google_gender_select, try_google_month_select
from .prompts import GENDER_OPTIONS, MONTH_NAMES
from .web_owner_profile import WebOwnerProfile

if TYPE_CHECKING:
    from playwright.sync_api import Page

# Playwright timeouts (ms). Keep in sync with planner expectations where noted.
_DEFAULT_WAIT_MS = 1000
_MIN_WAIT_MS = 100
_MAX_WAIT_MS = 300_000
_GOTO_TIMEOUT_MS = 30_000
_LOCATOR_TIMEOUT_MS = 10_000
_LOCATOR_SHORT_TIMEOUT_MS = 5_000
_AFTER_CUSTOM_SELECT_OPEN_MS = 700


def action_signature(action: dict[str, Any]) -> str:
    """Return a stable string key for deduplicating or comparing planned actions.

    Concatenates the main action fields so two logically identical plans
    produce the same signature even if other keys differ. Values are coerced
    with ``str()`` so missing keys still participate consistently.
    """
    if not isinstance(action, dict):
        msg = f"action must be a dict, got {type(action).__name__}"
        raise TypeError(msg)
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
    """Pick a single heuristic action when the model output is unusable.

    Uses URL and page title from ``snapshot`` to guess the next safe step
    (e.g. Google birthday page → focus month control; generic Google flow →
    Next; otherwise a short wait). Returns a dict in the same shape as planner
    actions so it can be passed to :func:`run_action`.
    """
    if not isinstance(snapshot, dict):
        msg = f"snapshot must be a dict, got {type(snapshot).__name__}"
        raise TypeError(msg)
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


def _is_real_number(value: Any) -> bool:
    """True for int/float excluding bool (bool is a subclass of int in Python)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _clamp_wait_ms(raw: Any, *, default: int = _DEFAULT_WAIT_MS) -> int:
    """Normalize wait duration to a finite integer in ``[_MIN_WAIT_MS, _MAX_WAIT_MS]``."""
    if raw is None:
        return default
    if not _is_real_number(raw):
        return default
    if math.isnan(raw) or math.isinf(raw):
        return default
    bounded = max(_MIN_WAIT_MS, min(_MAX_WAIT_MS, int(raw)))
    return bounded


def _post_action_sleep_ms(wait_ms: Any) -> int | None:
    """Milliseconds for optional post-click sleep, or None to skip.

    Unlike standalone ``wait``, sub-100ms values are allowed here so planners
    can use short UI-settling delays after clicks.
    """
    if not (_is_real_number(wait_ms) and wait_ms > 0):
        return None
    if math.isnan(wait_ms) or math.isinf(wait_ms):
        return None
    return max(1, min(_MAX_WAIT_MS, int(wait_ms)))


def _optional_post_wait(page: Page, wait_ms: Any) -> None:
    """If ``wait_ms`` is a positive finite number, block for that many milliseconds."""
    n = _post_action_sleep_ms(wait_ms)
    if n is not None:
        page.wait_for_timeout(n)


def _selector_targets_month_field(selector: str) -> bool:
    """Heuristic: selector string is meant to open or hit the month control."""
    lowered = selector.lower()
    return (
        "month" in lowered
        or "aria-label='month'" in lowered
        or 'aria-label="month"' in lowered
        or ":nth-of-type(1)" in lowered
    )


def _selector_targets_gender_field(selector: str) -> bool:
    """Heuristic: selector string is meant to open or hit the gender control."""
    lowered = selector.lower()
    return (
        "gender" in lowered
        or "aria-label='gender'" in lowered
        or 'aria-label="gender"' in lowered
        or ":nth-of-type(2)" in lowered
    )


def _try_click_list_item_by_text(page: Page, text: str, *, visible_timeout_ms: int = 2000) -> bool:
    """Click the first visible list/menu option whose text contains ``text``."""
    for list_sel in ("li", "[role='option']", "[role='menuitem']"):
        try:
            candidate = page.locator(list_sel).filter(has_text=text).first
            if candidate.is_visible(timeout=visible_timeout_ms):
                candidate.click(timeout=_LOCATOR_SHORT_TIMEOUT_MS)
                return True
        except Exception:  # noqa: BLE001 — best-effort across selector strategies
            continue
    return False


def _type_text_from_action(text: Any, value: Any) -> str:
    """Resolve the string to type: prefer ``text``, then ``value``, including numeric ``value``."""
    if isinstance(text, str) and text:
        return text
    if isinstance(value, str) and value:
        return value
    if _is_real_number(value):
        return str(value)
    msg = "type action missing text/value."
    raise RuntimeError(msg)


def _run_goto(page: Page, url: Any) -> bool:
    """Navigate to ``url`` and wait for ``domcontentloaded``."""
    if not isinstance(url, str) or not url.strip():
        msg = "goto action missing non-empty url."
        raise RuntimeError(msg)
    page.goto(url.strip(), wait_until="domcontentloaded", timeout=_GOTO_TIMEOUT_MS)
    return True


def _run_click(page: Page, selector: Any, wait_ms: Any, owner_profile: WebOwnerProfile | None) -> bool:
    """Perform a click on the first matching locator, with Google-specific shortcuts."""
    if not isinstance(selector, str) or not selector.strip():
        msg = "click action missing non-empty selector."
        raise RuntimeError(msg)
    selector = selector.strip()
    if selector == "button:has-text('Next')" and try_google_click_next(page):
        _optional_post_wait(page, wait_ms)
        return True
    page.locator(selector).first.click(timeout=_LOCATOR_TIMEOUT_MS)
    _optional_post_wait(page, wait_ms)
    if owner_profile is not None and _selector_targets_month_field(selector):
        if try_google_month_select(page, owner_profile.birth_month):
            return True
    if owner_profile is not None and _selector_targets_gender_field(selector):
        if try_google_gender_select(page, owner_profile.gender):
            return True
    return True


def _run_type(page: Page, selector: Any, text: Any, value: Any) -> bool:
    """Fill the first matching element with text from ``text`` or ``value``."""
    if not isinstance(selector, str) or not selector.strip():
        msg = "type action missing non-empty selector."
        raise RuntimeError(msg)
    text_value = _type_text_from_action(text, value)
    page.locator(selector.strip()).first.fill(text_value, timeout=_LOCATOR_TIMEOUT_MS)
    return True


def _run_select_option(page: Page, selector: Any, value: Any) -> bool:
    """Select an option on a native ``<select>`` or approximate custom dropdowns."""
    if not isinstance(selector, str) or not selector.strip():
        msg = "select_option action missing non-empty selector."
        raise RuntimeError(msg)
    if not isinstance(value, str) or not value.strip():
        msg = "select_option action missing non-empty value."
        raise RuntimeError(msg)
    value = value.strip()
    locator = page.locator(selector.strip()).first
    try:
        locator.select_option(value=value, timeout=_LOCATOR_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        try:
            locator.select_option(label=value, timeout=_LOCATOR_TIMEOUT_MS)
        except Exception:  # noqa: BLE001
            locator.click(timeout=_LOCATOR_TIMEOUT_MS)
            page.wait_for_timeout(_AFTER_CUSTOM_SELECT_OPEN_MS)
            if _try_click_list_item_by_text(page, value):
                return True
            try:
                page.get_by_text(value, exact=True).first.click(timeout=_LOCATOR_TIMEOUT_MS)
            except Exception as exc:  # noqa: BLE001
                msg = f"select_option could not choose value {value!r}: {exc}"
                raise RuntimeError(msg) from exc
    return True


def _run_click_text(page: Page, target_text: Any) -> bool:
    """Click visible text or list option ``target_text`` (Google month/gender aware)."""
    if not isinstance(target_text, str) or not target_text.strip():
        msg = "click_text action missing non-empty target_text."
        raise RuntimeError(msg)
    target_text = target_text.strip()
    if target_text in MONTH_NAMES and try_google_month_select(page, target_text):
        return True
    if target_text in GENDER_OPTIONS and try_google_gender_select(page, target_text):
        return True
    if _try_click_list_item_by_text(page, target_text):
        return True
    try:
        page.get_by_text(target_text, exact=True).first.click(timeout=_LOCATOR_SHORT_TIMEOUT_MS)
        return True
    except Exception:  # noqa: BLE001
        pass
    try:
        page.get_by_text(target_text, exact=False).first.click(timeout=_LOCATOR_TIMEOUT_MS)
        return True
    except Exception as exc:  # noqa: BLE001
        msg = f"click_text could not find clickable text {target_text!r}: {exc}"
        raise RuntimeError(msg) from exc


def _run_press(page: Page, selector: Any, key: Any) -> bool:
    """Send a key press to a focused element or page-wide if no selector."""
    if not isinstance(key, str) or not key.strip():
        msg = "press action missing non-empty key."
        raise RuntimeError(msg)
    key = key.strip()
    if isinstance(selector, str) and selector.strip():
        page.locator(selector.strip()).first.press(key, timeout=_LOCATOR_TIMEOUT_MS)
    else:
        page.keyboard.press(key)
    return True


def _run_wait(page: Page, wait_ms: Any) -> bool:
    """Block for a bounded duration (default if ``wait_ms`` is missing or invalid)."""
    page.wait_for_timeout(_clamp_wait_ms(wait_ms))
    return True


def run_action(
    page: Page,
    action: dict[str, Any],
    *,
    owner_profile: WebOwnerProfile | None = None,
) -> bool:
    """Execute one planner action on ``page``.

    When ``owner_profile`` is set, Google birthday-flow click shortcuts use the owner's
    ``birth_month`` and ``gender`` instead of any baked-in defaults.

    Returns:
        ``False`` only for ``action: "done"`` (caller should stop the loop).
        ``True`` for all other handled actions, including navigation and waits.

    Raises:
        TypeError: If ``action`` is not a mapping.
        RuntimeError: On invalid payloads, unknown action kinds, or unrecoverable UI errors.
    """
    if not isinstance(action, dict):
        msg = f"action must be a dict, got {type(action).__name__}"
        raise TypeError(msg)

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
        return _run_goto(page, url)
    if kind == "click":
        return _run_click(page, selector, wait_ms, owner_profile)
    if kind == "type":
        return _run_type(page, selector, text, value)
    if kind == "select_option":
        return _run_select_option(page, selector, value)
    if kind == "click_text":
        return _run_click_text(page, target_text)
    if kind == "press":
        return _run_press(page, selector, key)
    if kind == "wait":
        return _run_wait(page, wait_ms)
    msg = f"Unknown action type: {kind!r}"
    raise RuntimeError(msg)
