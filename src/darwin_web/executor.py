from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from playwright.sync_api import ElementHandle, Locator, Page

from darwin_web.playbook import Playbook, PlaybookStep
from darwin_web.selectors import css_path_for_element
from darwin_web.telegram_hil import (
    coerce_bool,
    coerce_max_wait_s,
    notify_owner_request_human,
    telegram_hil_env_enabled,
)

_DOM_META_JS = r"""(el) => {
  if (!(el instanceof Element)) return {};
  return {
    tag: el.tagName.toLowerCase(),
    id: el.id || "",
    name: el.getAttribute("name") || "",
    type: el.getAttribute("type") || "",
    role: el.getAttribute("role") || "",
    aria_label: el.getAttribute("aria-label") || "",
    placeholder: el.getAttribute("placeholder") || "",
  };
}"""


def _ref_locator(page: Page, ref: int):
    return page.locator(f'[data-darwin-web-ref="{ref}"]')


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be int")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip(), 10)
        except ValueError as exc:
            raise ValueError(f"{field} must be int") from exc
    raise ValueError(f"{field} must be int, got {type(value).__name__}")


def _redundant_text_fill_should_skip(*, current: str | None, desired: str) -> bool:
    """True when typing ``desired`` would not change the control (anti-loop guard)."""
    if current is None:
        return False
    return current.strip() == desired.strip()


def _short_url_for_errors(page: Page, *, max_len: int = 96) -> str:
    try:
        u = page.url.strip()
    except Exception:  # noqa: BLE001
        return ""
    if len(u) <= max_len:
        return u
    return u[: max_len - 1] + "…"


def _planner_description(action: dict[str, Any], fallback: str) -> str:
    d = action.get("describe")
    if isinstance(d, str) and d.strip():
        return d.strip()
    return fallback


def dom_fields_for_element(handle: ElementHandle, *, selector: str) -> dict[str, Any]:
    """DOM metadata for recipe YAML (selector is the machine targeting instruction)."""
    raw = handle.evaluate(_DOM_META_JS)
    if not isinstance(raw, dict):
        return {"selector": selector}
    out: dict[str, Any] = {"selector": selector}
    for key in ("tag", "id", "name", "type", "role", "aria_label", "placeholder"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    return out


def _select_option_on_locator(loc: Locator, value: str, *, timeout_ms: int) -> None:
    """Pick an option on a native ``<select>`` (try ``value=`` then ``label=``)."""
    try:
        loc.select_option(value=value, timeout=timeout_ms)
    except Exception:  # noqa: BLE001 — option mismatch; try label match
        loc.select_option(label=value, timeout=timeout_ms)


def _pick_role_option(page: Page, label: str, *, timeout_ms: int) -> str | None:
    """Click a visible ``role=option`` by accessible name. Returns error string or ``None``."""
    lab = label.strip()
    if not lab:
        return "pick_option: empty label"
    try:
        exact = page.get_by_role("option", name=lab, exact=True)
        if exact.count() > 0:
            exact.first.click(timeout=timeout_ms)
            return None
        loose = page.get_by_role("option", name=lab, exact=False)
        if loose.count() > 0:
            loose.first.click(timeout=timeout_ms)
            return None
    except Exception as exc:  # noqa: BLE001
        return f"pick_option: {exc}"
    return f"pick_option: no visible role=option matching {lab!r}"


def run_planner_action(
    page: Page,
    action: dict[str, Any],
    *,
    default_timeout_ms: float = 12_000,
    vision_png_path: Path | None = None,
) -> tuple[bool, PlaybookStep | None, str | None]:
    """Execute one planner *action* dict.

    Returns:
        (continue_loop, playbook_step_recorded, error_message)
    """
    op = action.get("op")
    if not isinstance(op, str):
        return True, None, "action.op must be string"

    if op == "done":
        return False, None, None

    if op == "request_human":
        reason = action.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return True, None, "request_human.reason must be a non-empty string"
        instructions = action.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            instructions = action.get("describe")
        if not isinstance(instructions, str) or not instructions.strip():
            return (
                True,
                None,
                "request_human.instructions must be a non-empty string (or use describe)",
            )
        if not telegram_hil_env_enabled():
            return (
                True,
                None,
                "request_human: Telegram HIL is not configured "
                "(set DARWIN_WEB_TELEGRAM_BOT_TOKEN and DARWIN_WEB_TELEGRAM_CHAT_ID; "
                "optional DARWIN_WEB_TELEGRAM_HIL=1)",
            )
        try:
            page_url = page.url
        except Exception as exc:  # noqa: BLE001
            return True, None, f"request_human: could not read page.url: {exc}"
        wait_for_owner = coerce_bool(action.get("wait_for_owner"), default=True)
        max_wait_s = coerce_max_wait_s(action.get("max_wait_s"), default=3600.0)
        err = notify_owner_request_human(
            reason=reason.strip(),
            instructions=instructions.strip(),
            page_url=page_url,
            image_path=vision_png_path,
            wait_for_owner=wait_for_owner,
            max_wait_s=max_wait_s,
        )
        if err:
            return True, None, err
        return True, None, None

    if op == "goto":
        url = action.get("url")
        if not isinstance(url, str) or not url.strip():
            return True, None, "goto requires non-empty url string"
        u = url.strip()
        page.goto(u, wait_until="domcontentloaded", timeout=default_timeout_ms)
        desc = _planner_description(action, f"Open page {u}")
        return True, PlaybookStep(op="goto", description=desc, dom={"url": u}, url=u), None

    if op == "wait_ms":
        ms = _as_int(action.get("ms", 500), "ms")
        ms = max(0, min(ms, 60_000))
        page.wait_for_timeout(ms)
        desc = _planner_description(action, f"Wait {ms} ms for the page to settle")
        return True, PlaybookStep(op="wait_ms", description=desc, dom={"ms": ms}, ms=ms), None

    if op == "scroll_into_view":
        ref = _as_int(action.get("ref"), "ref")
        loc = _ref_locator(page, ref)
        loc.first.scroll_into_view_if_needed(timeout=int(default_timeout_ms))
        handle = loc.first.element_handle()
        if handle is None:
            return True, None, f"scroll_into_view: no element for ref {ref}"
        sel = css_path_for_element(handle)
        dom = dom_fields_for_element(handle, selector=sel)
        handle.dispose()
        desc = _planner_description(action, f"Scroll target into view ({dom.get('tag', 'element')})")
        return True, PlaybookStep(op="scroll_into_view", description=desc, dom=dom, selector=sel), None

    if op == "select_option":
        ref = _as_int(action.get("ref"), "ref")
        value = action.get("value")
        if not isinstance(value, str):
            return True, None, "select_option.value must be string"
        loc = _ref_locator(page, ref).first
        loc.scroll_into_view_if_needed(timeout=int(default_timeout_ms))
        handle = loc.element_handle()
        if handle is None:
            return True, None, f"select_option: no element for ref {ref}"
        if not handle.evaluate("(el) => el instanceof HTMLSelectElement"):
            handle.dispose()
            return True, None, f"select_option: ref {ref} is not a native <select> (use click/fill for custom widgets)"
        sel = css_path_for_element(handle)
        dom = dom_fields_for_element(handle, selector=sel)
        handle.dispose()
        _select_option_on_locator(loc, value, timeout_ms=int(default_timeout_ms))
        dom["selected_value"] = value
        desc = _planner_description(
            action,
            f"Select option {value!r} on {dom.get('tag', 'select')}",
        )
        return True, PlaybookStep(
            op="select_option",
            description=desc,
            dom=dom,
            selector=sel,
            value=value,
        ), None

    if op == "pick_option":
        label = action.get("label")
        if not isinstance(label, str) or not label.strip():
            label = action.get("text")
        if not isinstance(label, str) or not label.strip():
            label = action.get("value")
        if not isinstance(label, str) or not label.strip():
            return True, None, "pick_option requires label|text|value (non-empty string)"
        lab = label.strip()
        err = _pick_role_option(page, lab, timeout_ms=int(default_timeout_ms))
        if err:
            return True, None, err
        desc = _planner_description(
            action,
            f"Pick listbox option {lab!r}",
        )
        return True, PlaybookStep(
            op="pick_option",
            description=desc,
            dom={"option_label": lab},
            selector=None,
            value=lab,
        ), None

    if op == "click":
        ref = _as_int(action.get("ref"), "ref")
        loc = _ref_locator(page, ref).first
        loc.scroll_into_view_if_needed(timeout=int(default_timeout_ms))
        handle = loc.element_handle()
        if handle is None:
            return True, None, f"click: no element for ref {ref}"
        sel = css_path_for_element(handle)
        dom = dom_fields_for_element(handle, selector=sel)
        loc.click(timeout=default_timeout_ms)
        handle.dispose()
        desc = _planner_description(action, f"Click {dom.get('tag', 'element')}")
        return True, PlaybookStep(op="click", description=desc, dom=dom, selector=sel), None

    if op == "fill":
        ref = _as_int(action.get("ref"), "ref")
        value = action.get("value")
        if not isinstance(value, str):
            return True, None, "fill.value must be string"
        clear_first = bool(action.get("clear_first", True))
        loc = _ref_locator(page, ref).first
        loc.scroll_into_view_if_needed(timeout=int(default_timeout_ms))
        handle = loc.element_handle()
        if handle is None:
            return True, None, f"fill: no element for ref {ref}"
        sel = css_path_for_element(handle)
        dom = dom_fields_for_element(handle, selector=sel)
        is_select = bool(handle.evaluate("(el) => el instanceof HTMLSelectElement"))
        handle.dispose()
        if is_select:
            _select_option_on_locator(loc, value, timeout_ms=int(default_timeout_ms))
            dom["selected_value"] = value
            desc = _planner_description(
                action,
                f"Select option {value!r} in dropdown ({sel})",
            )
            return True, PlaybookStep(
                op="select_option",
                description=desc,
                dom=dom,
                selector=sel,
                value=value,
            ), None
        inp_type = str(dom.get("type", "")).lower()
        if inp_type not in ("checkbox", "radio", "file", "button", "submit", "hidden", "range", "color"):
            try:
                cur = loc.input_value(timeout=int(min(default_timeout_ms, 8_000)))
            except Exception:  # noqa: BLE001
                cur = ""
            if _redundant_text_fill_should_skip(current=cur, desired=value):
                loc_hint = _short_url_for_errors(page)
                loc_tail = f" [page: {loc_hint}]" if loc_hint else ""
                return (
                    True,
                    None,
                    f"fill skipped: ref {ref} already contains this exact text{loc_tail}; do not repeat on this screen. "
                    "Use pick_option if a listbox is open, otherwise click Next or fill a different empty field.",
                )
        dom["entered_text"] = value
        if clear_first:
            loc.fill("")
        loc.fill(value, timeout=default_timeout_ms)
        desc = _planner_description(
            action,
            f"Enter text into {dom.get('tag', 'field')} (selector {sel})",
        )
        return True, PlaybookStep(
            op="fill",
            description=desc,
            dom=dom,
            selector=sel,
            value=value,
            clear_first=clear_first,
        ), None

    if op == "press":
        key = action.get("key")
        if not isinstance(key, str) or not key.strip():
            return True, None, "press.key must be non-empty string"
        k = key.strip()
        ref_raw = action.get("ref")
        sel: str | None = None
        dom: dict[str, Any] | None = None
        if ref_raw is not None:
            ref = _as_int(ref_raw, "ref")
            loc = _ref_locator(page, ref).first
            loc.scroll_into_view_if_needed(timeout=int(default_timeout_ms))
            handle = loc.element_handle()
            if handle is None:
                return True, None, f"press: no element for ref {ref}"
            sel = css_path_for_element(handle)
            dom = dom_fields_for_element(handle, selector=sel)
            loc.click(timeout=default_timeout_ms)
            handle.dispose()
        desc = _planner_description(action, f"Press keyboard key {k!r}")
        if dom is None:
            dom = {"key": k}
        else:
            dom = {**dom, "key": k}
        return True, PlaybookStep(op="press", description=desc, dom=dom, key=k, selector=sel), None

    return True, None, f"unknown op: {op}"


def replay_step(page: Page, step: PlaybookStep, *, default_timeout_ms: float = 12_000) -> None:
    """Run a single :class:`PlaybookStep` (deterministic; uses ``selector`` / ``url`` / ``key``)."""
    if step.op == "goto":
        if not step.url:
            raise ValueError("goto step missing url")
        page.goto(step.url, wait_until="domcontentloaded", timeout=default_timeout_ms)
        return
    if step.op == "wait_ms":
        ms = step.ms if step.ms is not None else 0
        page.wait_for_timeout(ms)
        return
    if step.op == "select_option":
        if not step.selector or step.value is None:
            raise ValueError("select_option step missing selector or value")
        loc = page.locator(step.selector).first
        loc.scroll_into_view_if_needed(timeout=int(default_timeout_ms))
        _select_option_on_locator(loc, step.value, timeout_ms=int(default_timeout_ms))
        return
    if step.op == "pick_option":
        if not step.value:
            raise ValueError("pick_option step missing value (option label)")
        err = _pick_role_option(page, step.value, timeout_ms=int(default_timeout_ms))
        if err:
            raise RuntimeError(err)
        return
    if step.op in ("click", "fill", "scroll_into_view"):
        if not step.selector:
            raise ValueError(f"{step.op} step missing selector")
        loc = page.locator(step.selector).first
        loc.scroll_into_view_if_needed(timeout=int(default_timeout_ms))
        if step.op == "click":
            loc.click(timeout=default_timeout_ms)
            return
        if step.op == "scroll_into_view":
            return
        if step.op == "fill":
            if step.value is None:
                raise ValueError("fill step missing value")
            if step.clear_first:
                loc.fill("")
            loc.fill(step.value, timeout=default_timeout_ms)
            return
    if step.op == "press":
        if not step.key:
            raise ValueError("press step missing key")
        if step.selector:
            page.locator(step.selector).first.click(timeout=default_timeout_ms)
        page.keyboard.press(step.key)
        return
    raise ValueError(f"unsupported op: {step.op}")


def replay_playbook(page: Page, steps: list[PlaybookStep], *, pause_ms: int = 0) -> None:
    for st in steps:
        replay_step(page, st, default_timeout_ms=12_000)
        if pause_ms > 0:
            time.sleep(pause_ms / 1000.0)


def execute_recipe_yaml(page: Page, recipe_path: str | Path, *, pause_ms: int = 0) -> None:
    """Load a YAML (or legacy JSON) recipe and replay all steps without an LLM."""
    pb = Playbook.read(Path(recipe_path))
    replay_playbook(page, pb.steps, pause_ms=pause_ms)
