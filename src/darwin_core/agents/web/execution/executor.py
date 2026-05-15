from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import ElementHandle, Locator, Page
from playwright._impl._errors import TargetClosedError
from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError

from darwin_core.agents.web.browser.snapshot import PageClosed

from darwin_core.agents.web.browser.browser_session import (
    get_browser_cdp_ws_url,
    get_browser_live_url,
    get_browser_server_url,
)
from darwin_core.agents.web.integrations.genhash import reset_pw_cache, try_expand_fill
from darwin_core.agents.web.playbook.playbook import Playbook, PlaybookStep
from darwin_core.agents.web.browser.selectors import css_path_for_element
from darwin_core.agents.web.integrations.telegram_hil import (
    coerce_bool,
    coerce_max_wait_s,
    notify_owner_request_human,
    owner_telegram_reply_hint_plain,
    telegram_hil_env_enabled,
)


def _post_click_settle_ms() -> int:
    """Pause after UI clicks so SPAs can paint (next planner snapshot matches the new step)."""
    raw = os.getenv("DARWIN_WEB_POST_CLICK_MS", "1000").strip()
    try:
        ms = int(raw, 10)
    except ValueError:
        return 1000
    return max(0, min(ms, 10_000))


def _post_click_settle(page: Page) -> None:
    ms = _post_click_settle_ms()
    if ms <= 0:
        return
    try:
        page.wait_for_timeout(ms)
    except Exception:  # noqa: BLE001
        pass


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


def _parse_ref(action: dict[str, Any], *, op: str) -> tuple[int | None, str | None]:
    """Return ``(ref, error)``; *error* is set when ``ref`` is missing or not coercible to int."""
    raw = action.get("ref")
    if raw is None:
        return None, f"{op}: missing ref (integer from the element list)"
    try:
        return _as_int(raw, "ref"), None
    except ValueError as exc:
        return None, f"{op}: {exc}"


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


_WORD_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# Generic UI placeholder words that commonly appear alongside a real selected value inside
# a combobox (e.g. "Mes Enero", "Month January", "Select March"). Their presence alone should
# NOT convince us that the target option has already been picked.
_COMBOBOX_LABEL_NOISE: frozenset[str] = frozenset(
    {
        # English
        "month", "months", "select", "choose", "pick", "year", "years",
        "day", "date", "gender", "country", "language",
        # Spanish
        "mes", "meses", "selecciona", "seleccionar", "elegir", "elige",
        "año", "años", "dia", "dia", "fecha", "genero", "pais", "idioma",
        # French
        "mois", "choisir", "choisissez", "annee", "jour", "pays",
        # Portuguese
        "mês", "mes", "escolha", "selecione", "ano", "dia",
        # German
        "monat", "auswählen", "auswahlen", "jahr", "tag", "land",
        # Italian
        "mese", "scegli", "anno", "giorno", "paese",
    }
)


def _word_tokens(s: str) -> set[str]:
    """Lowercased letter-only tokens (Unicode); skips digits so day fields do not satisfy month picks."""
    return {m.group(0).lower() for m in _WORD_TOKEN_RE.finditer(s)}


def _pick_option_redundant_vs_combobox_blobs(label: str, blobs: list[str]) -> bool:
    """True when ``label`` is already the *sole meaningful value* shown on a combobox.

    The check is intentionally strict to avoid falsely skipping a pick_option call:

    - The combobox text must contain ALL of the label's word-tokens (it is selected/showing).
    - The *extra* tokens beyond the label must NOT all be generic UI noise words (e.g. "Mes",
      "Month", "Select"). If every extra word is noise, the combobox might just be a blank
      field with a placeholder — clicking the option row is still required.
    - Exact token match (label == combobox text) is explicitly **not** redundant: the combobox
      may just show the placeholder text matching the option name without being selected.
    """
    lab = label.strip()
    if not lab:
        return False
    need = _word_tokens(lab)
    if not need:
        return False
    # Very short single tokens (< 3 chars) are not reliable discriminators.
    if len(need) == 1 and len(next(iter(need))) < 3:
        return False
    for blob in blobs:
        blob_tok = _word_tokens(blob)
        if not blob_tok:
            continue
        # All needed tokens must be present in the combobox text.
        if not need <= blob_tok:
            continue
        extra = blob_tok - need
        # Exact match: combobox text == label tokens — not redundant (could be placeholder).
        if not extra:
            continue
        # If every extra token is a known UI noise word, the combobox is likely just showing
        # the field label alongside what the user typed/hasn't-typed-yet — not already selected.
        if extra <= _COMBOBOX_LABEL_NOISE:
            continue
        return True
    return False


def _visible_combobox_inner_text_blobs(page: Page) -> list[str]:
    """Human-visible strings from ``role=combobox`` nodes (Material / ARIA widgets often hide options until open)."""
    out: list[str] = []
    try:
        root = page.locator('[role="combobox"]')
        n = min(int(root.count()), 40)
    except Exception:  # noqa: BLE001
        return out
    for i in range(n):
        loc = root.nth(i)
        try:
            if not loc.is_visible(timeout=300):
                continue
        except Exception:  # noqa: BLE001
            continue
        raw = ""
        try:
            raw = str(loc.inner_text(timeout=800) or "")
        except Exception:  # noqa: BLE001
            raw = ""
        av = ""
        try:
            av = str(loc.get_attribute("aria-valuetext") or "")
        except Exception:  # noqa: BLE001
            av = ""
        out.append(f"{raw} {av}".strip())
    return out


_MONTH_EN_TO_ES: dict[str, str] = {
    "january": "enero",
    "february": "febrero",
    "march": "marzo",
    "april": "abril",
    "may": "mayo",
    "june": "junio",
    "july": "julio",
    "august": "agosto",
    "september": "septiembre",
    "october": "octubre",
    "november": "noviembre",
    "december": "diciembre",
}


def _label_pick_variants(label: str) -> list[str]:
    """Try English month names and Spanish UI spellings (and vice versa)."""
    lab = label.strip()
    if not lab:
        return []
    out: list[str] = [lab]
    low = lab.lower()
    if low in _MONTH_EN_TO_ES:
        alt = _MONTH_EN_TO_ES[low]
        if alt not in out:
            out.append(alt.capitalize() if lab[:1].isupper() else alt)
    for en, es in _MONTH_EN_TO_ES.items():
        if low == es and en.capitalize() not in out:
            out.append(en.capitalize())
        if low == es and en not in out:
            out.append(en)
    return out


def _click_visible_text_option(page: Page, label: str, *, timeout_ms: int) -> str | None:
    """Click a small visible node whose text equals *label* (Fluent / portal menus)."""
    lab = label.strip()
    if not lab:
        return "empty label"
    pat = re.compile(r"^\s*" + re.escape(lab) + r"\s*$", re.IGNORECASE | re.UNICODE)
    last_err: str | None = None
    container_selectors = (
        '[role="listbox"]',
        '[role="menu"]',
        '[id*="listbox" i]',
        '[id*="Listbox"]',
        '[class*="ms-Callout"]',
        '[class*="fui-Listbox"]',
        '[data-is-focusable="true"]',
    )
    for container_sel in container_selectors:
        try:
            containers = page.locator(container_sel)
            n_c = min(int(containers.count()), 12)
        except Exception:  # noqa: BLE001
            continue
        for ci in range(n_c):
            cont = containers.nth(ci)
            try:
                if not cont.is_visible(timeout=400):
                    continue
            except Exception:  # noqa: BLE001
                continue
            try:
                rows = cont.locator("*").filter(has_text=pat)
                n = int(rows.count())
            except Exception:  # noqa: BLE001
                continue
            for i in range(n - 1, -1, -1):
                row = rows.nth(i)
                try:
                    if not row.is_visible(timeout=400):
                        continue
                    box = row.bounding_box()
                    if box is not None and box.get("height", 0) > 120:
                        continue
                    row.click(timeout=timeout_ms)
                    return None
                except Exception as exc:  # noqa: BLE001
                    last_err = str(exc)
    try:
        rows = page.get_by_text(pat)
        n = min(int(rows.count()), 40)
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    for i in range(n - 1, -1, -1):
        row = rows.nth(i)
        try:
            if not row.is_visible(timeout=400):
                continue
            box = row.bounding_box()
            if box is not None and box.get("height", 0) > 120:
                continue
            row.click(timeout=timeout_ms)
            return None
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
    if last_err:
        return f"visible text click failed: {last_err}"
    return f"no visible text row matching {lab!r}"


def _wait_for_dropdown_surface(page: Page, *, timeout_ms: int) -> None:
    for menu_sel in ('[role="listbox"]', '[role="menu"]', '[id*="listbox" i]'):
        try:
            page.locator(menu_sel).first.wait_for(state="visible", timeout=min(2500, timeout_ms))
            return
        except Exception:  # noqa: BLE001
            continue


def _combobox_pick_at_ref(
    page: Page,
    ref: int,
    label: str,
    *,
    default_timeout_ms: float,
) -> tuple[str | None, str | None]:
    """Open combobox *ref* and choose *label*. Returns (selector, error)."""
    timeout_ms = int(default_timeout_ms)
    loc = _ref_locator(page, ref).first
    loc.scroll_into_view_if_needed(timeout=timeout_ms)
    handle = loc.element_handle()
    if handle is None:
        return None, f"combobox_pick: no element for ref {ref}"
    sel = css_path_for_element(handle)
    handle.dispose()

    if _pick_option_redundant_vs_combobox_blobs(
        label, [str(loc.inner_text(timeout=800) or ""), str(loc.get_attribute("aria-valuetext") or "")]
    ):
        return sel, None

    expanded: str | None = None
    try:
        expanded = loc.get_attribute("aria-expanded")
    except Exception:  # noqa: BLE001
        expanded = None

    def try_pick_all_variants() -> str | None:
        last: str | None = None
        for variant in _label_pick_variants(label):
            err = _pick_role_option(page, variant, timeout_ms=timeout_ms)
            if err is None:
                return None
            last = err
            err2 = _click_visible_text_option(page, variant, timeout_ms=timeout_ms)
            if err2 is None:
                return None
            last = err2
        if label.strip().isdigit():
            try:
                page.keyboard.type(label.strip())
                page.wait_for_timeout(200)
                page.keyboard.press("Enter")
                return None
            except Exception as exc:  # noqa: BLE001
                last = str(exc)
        return last

    if expanded == "true":
        err_open = try_pick_all_variants()
        _post_click_settle(page)
        if err_open is None:
            return sel, None
        return sel, err_open

    err_before_open = try_pick_all_variants()
    if err_before_open is None:
        _post_click_settle(page)
        return sel, None

    try:
        loc.click(timeout=default_timeout_ms)
    except Exception as exc:  # noqa: BLE001
        return sel, f"combobox_pick: could not click ref {ref}: {exc}"
    page.wait_for_timeout(400)
    _wait_for_dropdown_surface(page, timeout_ms=timeout_ms)

    err_after_open = try_pick_all_variants()
    _post_click_settle(page)
    if err_after_open is None:
        return sel, None
    return sel, err_after_open or f"combobox_pick: could not select {label.strip()!r}"


def _pick_role_option(page: Page, label: str, *, timeout_ms: int) -> str | None:
    """Click a visible ``role=option`` or ``role=menuitem`` row by accessible or visible text.

    Falls back to scanning child elements of open ``role=listbox`` panels for custom month/date
    pickers that do not use ``role=option`` on individual rows.
    """
    lab = label.strip()
    if not lab:
        return "pick_option: empty label"
    pat = re.compile(r"^\s*" + re.escape(lab) + r"\s*$", re.IGNORECASE | re.UNICODE)
    last_click_err: str | None = None

    def try_role(role: str) -> bool:
        nonlocal last_click_err
        try:
            exact = page.get_by_role(role, name=lab, exact=True)  # type: ignore[arg-type]
            if exact.count() > 0:
                exact.first.click(timeout=timeout_ms)
                return True
            loose = page.get_by_role(role, name=lab, exact=False)  # type: ignore[arg-type]
            if loose.count() > 0:
                loose.first.click(timeout=timeout_ms)
                return True
            by_row = page.get_by_role(role).filter(has_text=pat)  # type: ignore[arg-type]
            if by_row.count() > 0:
                by_row.first.click(timeout=timeout_ms)
                return True
        except Exception as exc:  # noqa: BLE001
            last_click_err = str(exc)
            return False
        return False

    try:
        if try_role("option"):
            return None
        if try_role("menuitem"):
            return None
    except Exception as exc:  # noqa: BLE001
        return f"pick_option: {exc}"

    # Fallback: scan visible role=listbox containers for child rows that contain the label text.
    # Some custom date/month pickers render rows as <li>, <div>, or <span> without role=option.
    try:
        listboxes = page.locator('[role="listbox"]')
        n_lb = min(int(listboxes.count()), 10)
        for i in range(n_lb):
            lb = listboxes.nth(i)
            try:
                if not lb.is_visible(timeout=300):
                    continue
            except Exception:  # noqa: BLE001
                continue
            # Try child elements that match the label text.
            child = lb.locator("*").filter(has_text=pat)
            try:
                cnt = child.count()
            except Exception:  # noqa: BLE001
                continue
            if cnt > 0:
                try:
                    child.first.click(timeout=timeout_ms)
                    return None
                except Exception as exc:  # noqa: BLE001
                    last_click_err = str(exc)
    except Exception:  # noqa: BLE001
        pass

    # Only treat as redundant if the option is already selected AND the combobox text indicates
    # it via meaningful non-noise extra tokens (see _pick_option_redundant_vs_combobox_blobs).
    if _pick_option_redundant_vs_combobox_blobs(lab, _visible_combobox_inner_text_blobs(page)):
        return None

    def try_pick_variant(variant: str) -> bool:
        nonlocal last_click_err
        vpat = re.compile(r"^\s*" + re.escape(variant) + r"\s*$", re.IGNORECASE | re.UNICODE)
        try:
            for role in ("option", "menuitem"):
                exact = page.get_by_role(role, name=variant, exact=True)  # type: ignore[arg-type]
                if exact.count() > 0:
                    exact.first.click(timeout=timeout_ms)
                    return True
                loose = page.get_by_role(role, name=variant, exact=False)  # type: ignore[arg-type]
                if loose.count() > 0:
                    loose.first.click(timeout=timeout_ms)
                    return True
                by_row = page.get_by_role(role).filter(has_text=vpat)  # type: ignore[arg-type]
                if by_row.count() > 0:
                    by_row.first.click(timeout=timeout_ms)
                    return True
        except Exception as exc:  # noqa: BLE001
            last_click_err = str(exc)
        err_txt = _click_visible_text_option(page, variant, timeout_ms=timeout_ms)
        return err_txt is None

    for variant in _label_pick_variants(lab):
        if try_pick_variant(variant):
            return None

    if last_click_err:
        return f"pick_option: found a matching row but click failed: {last_click_err}"
    return f"pick_option: no visible role=option, role=menuitem, or listbox row matching {lab!r}"


def _run_planner_action_inner(
    page: Page,
    action: dict[str, Any],
    *,
    default_timeout_ms: float = 12_000,
    vision_png_path: Path | None = None,
) -> tuple[bool, PlaybookStep | None, str | None, dict[str, Any] | None]:
    op = action.get("op")
    if not isinstance(op, str):
        return True, None, "action.op must be string", None

    if op == "done":
        return False, None, None, None

    if op == "request_human":
        reason = action.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return True, None, "request_human.reason must be a non-empty string", None
        instructions = action.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            instructions = action.get("describe")
        if not isinstance(instructions, str) or not instructions.strip():
            return (
                True,
                None,
                "request_human.instructions must be a non-empty string (or use describe)",
                None,
            )
        if not telegram_hil_env_enabled():
            return (
                True,
                None,
                "request_human: Telegram HIL is not configured "
                "(set DARWIN_WEB_TELEGRAM_BOT_TOKEN and DARWIN_WEB_TELEGRAM_CHAT_ID; "
                "optional DARWIN_WEB_TELEGRAM_HIL=1)",
                {
                    "request_human": {
                        "reason": reason.strip(),
                        "instructions": instructions.strip(),
                        "telegram": {"configured": False, "hint_message": owner_telegram_reply_hint_plain()},
                    }
                },
            )
        try:
            page_url = page.url
        except Exception as exc:  # noqa: BLE001
            return True, None, f"request_human: could not read page.url: {exc}", None
        wait_for_owner = coerce_bool(action.get("wait_for_owner"), default=True)
        max_wait_s = coerce_max_wait_s(action.get("max_wait_s"), default=3600.0)

        # Ensure we always have a screenshot for Telegram.
        # The pre-captured vision_png_path may be None if the earlier screenshot failed.
        image_for_telegram = vision_png_path
        if image_for_telegram is None or not image_for_telegram.is_file():
            try:
                import tempfile
                _tmp = Path(tempfile.mktemp(suffix=".png"))
                page.screenshot(path=str(_tmp), full_page=False)
                image_for_telegram = _tmp
            except Exception:  # noqa: BLE001
                image_for_telegram = None

        hil = notify_owner_request_human(
            reason=reason.strip(),
            instructions=instructions.strip(),
            page_url=page_url,
            image_path=image_for_telegram,
            wait_for_owner=wait_for_owner,
            max_wait_s=max_wait_s,
            browser_cdp_ws_url=get_browser_cdp_ws_url(),
            browser_live_url=get_browser_live_url(),
            browser_server_url=get_browser_server_url(),
        )
        meta = {
            "request_human": {
                "reason": reason.strip(),
                "instructions": instructions.strip(),
                "telegram": {
                    "configured": hil.telegram_configured,
                    "hil_kind": hil.hil_kind,
                    "browser_action_notice": hil.browser_action_notice,
                    "browser_cdp_ws_url": hil.browser_cdp_ws_url,
                    "browser_live_url": hil.browser_live_url,
                    "hint_message": hil.owner_reply_hint,
                    "owner_reply": hil.owner_reply,
                    "waited_for_owner": hil.waited_for_owner,
                    "error": hil.error,
                },
            }
        }
        if hil.error:
            return True, None, hil.error, meta
        return True, None, None, meta

    if op == "goto":
        url = action.get("url")
        if not isinstance(url, str) or not url.strip():
            return True, None, "goto requires non-empty url string", None
        u = url.strip()
        page.goto(u, wait_until="domcontentloaded", timeout=default_timeout_ms)
        reset_pw_cache()
        desc = _planner_description(action, f"Open page {u}")
        return True, PlaybookStep(op="goto", description=desc, dom={"url": u}, url=u), None, None

    if op == "go_back":
        try:
            resp = page.go_back(wait_until="domcontentloaded", timeout=default_timeout_ms)
        except Exception as exc:  # noqa: BLE001
            return True, None, f"go_back: browser back failed: {exc}", None
        if resp is None:
            return True, None, "go_back: no previous page in history", None
        reset_pw_cache()
        _post_click_settle(page)
        try:
            new_url = page.url
        except Exception:  # noqa: BLE001
            new_url = "unknown"
        desc = _planner_description(action, f"Navigate back to {new_url}")
        return True, PlaybookStep(op="go_back", description=desc, dom={"url": new_url}, url=new_url), None, None

    if op == "wait_ms":
        ms = _as_int(action.get("ms", 500), "ms")
        ms = max(0, min(ms, 60_000))
        page.wait_for_timeout(ms)
        desc = _planner_description(action, f"Wait {ms} ms for the page to settle")
        return True, PlaybookStep(op="wait_ms", description=desc, dom={"ms": ms}, ms=ms), None, None

    if op == "scroll_into_view":
        ref, ref_err = _parse_ref(action, op="scroll_into_view")
        if ref_err or ref is None:
            return True, None, ref_err, None
        loc = _ref_locator(page, ref)
        loc.first.scroll_into_view_if_needed(timeout=int(default_timeout_ms))
        handle = loc.first.element_handle()
        if handle is None:
            return True, None, f"scroll_into_view: no element for ref {ref}", None
        sel = css_path_for_element(handle)
        dom = dom_fields_for_element(handle, selector=sel)
        handle.dispose()
        desc = _planner_description(action, f"Scroll target into view ({dom.get('tag', 'element')})")
        return True, PlaybookStep(op="scroll_into_view", description=desc, dom=dom, selector=sel), None, None

    if op == "select_option":
        ref, ref_err = _parse_ref(action, op="select_option")
        if ref_err or ref is None:
            return True, None, ref_err, None
        value = action.get("value")
        if not isinstance(value, str):
            return True, None, "select_option.value must be string", None
        loc = _ref_locator(page, ref).first
        loc.scroll_into_view_if_needed(timeout=int(default_timeout_ms))
        handle = loc.element_handle()
        if handle is None:
            return True, None, f"select_option: no element for ref {ref}", None
        if not handle.evaluate("(el) => el instanceof HTMLSelectElement"):
            handle.dispose()
            return True, None, (
                f"select_option: ref {ref} is not a native <select> — use click on the combobox ref, "
                "then pick_option with the exact visible row text (not the field placeholder)."
            ), None
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
        ), None, None

    if op == "combobox_pick":
        ref, ref_err = _parse_ref(action, op="combobox_pick")
        if ref_err or ref is None:
            return True, None, ref_err, None
        label = action.get("label")
        if not isinstance(label, str) or not label.strip():
            label = action.get("text")
        if not isinstance(label, str) or not label.strip():
            label = action.get("value")
        if not isinstance(label, str) or not label.strip():
            return True, None, "combobox_pick requires label|text|value (non-empty string)", None
        lab = label.strip()
        sel, err = _combobox_pick_at_ref(page, ref, lab, default_timeout_ms=default_timeout_ms)
        if err:
            return True, None, err, None
        dom = {"selector": sel, "option_label": lab} if sel else {"option_label": lab}
        desc = _planner_description(action, f"Pick combobox option {lab!r}")
        return True, PlaybookStep(
            op="pick_option",
            description=desc,
            dom=dom,
            selector=sel,
            value=lab,
        ), None, None

    if op == "pick_option":
        label = action.get("label")
        if not isinstance(label, str) or not label.strip():
            label = action.get("text")
        if not isinstance(label, str) or not label.strip():
            label = action.get("value")
        if not isinstance(label, str) or not label.strip():
            return True, None, "pick_option requires label|text|value (non-empty string)", None
        lab = label.strip()
        err = _pick_role_option(page, lab, timeout_ms=int(default_timeout_ms))
        if err:
            return True, None, err, None
        _post_click_settle(page)
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
        ), None, None

    if op == "click":
        ref, ref_err = _parse_ref(action, op="click")
        if ref_err or ref is None:
            return True, None, ref_err, None
        loc = _ref_locator(page, ref).first
        loc.scroll_into_view_if_needed(timeout=int(default_timeout_ms))
        handle = loc.element_handle()
        if handle is None:
            return True, None, f"click: no element for ref {ref}", None
        sel = css_path_for_element(handle)
        dom = dom_fields_for_element(handle, selector=sel)

        # Guard: clicking an already-open combobox would toggle it closed,
        # causing a loop where the LLM opens → clicks trigger → closes → opens.
        role_l = str(dom.get("role", "")).lower()
        if role_l == "combobox":
            try:
                expanded = handle.get_attribute("aria-expanded")
            except Exception:  # noqa: BLE001
                expanded = None
            if expanded == "true":
                handle.dispose()
                return True, None, (
                    f"click: ref {ref} is a combobox already open (aria-expanded=true). "
                    "Clicking it again would close the dropdown. Instead, use "
                    'pick_option with the visible option text (e.g. {"op":"pick_option","label":"Enero","describe":"..."}), '
                    "or click the specific option ref from the element list."
                ), None

        inp_type = str(dom.get("type", "")).lower()
        if inp_type in ("checkbox", "radio"):
            check_err: str | None = None
            try:
                loc.check(timeout=default_timeout_ms)
            except Exception as exc:  # noqa: BLE001
                check_err = str(exc)
                label_clicked = False
                try:
                    label = handle.evaluate(
                        """(el) => {
                          const id = el.id;
                          if (id) {
                            const lab = document.querySelector('label[for="' + id + '"]');
                            if (lab) return lab;
                          }
                          let p = el.parentElement;
                          while (p) {
                            if (p.tagName && p.tagName.toLowerCase() === 'label') return p;
                            p = p.parentElement;
                          }
                          return null;
                        }"""
                    )
                    if label:
                        page.evaluate("(lab) => lab.click()", label)
                        label_clicked = True
                except Exception:  # noqa: BLE001
                    label_clicked = False
                if not label_clicked:
                    try:
                        loc.check(force=True, timeout=default_timeout_ms)
                        check_err = None
                    except Exception as force_exc:  # noqa: BLE001
                        handle.dispose()
                        return (
                            True,
                            None,
                            f"click/checkbox: ref {ref} failed ({check_err}); label and force check failed: {force_exc}",
                            None,
                        )
            handle.dispose()
            _post_click_settle(page)
            desc = _planner_description(action, f"Check {dom.get('tag', 'input')}")
            return True, PlaybookStep(op="click", description=desc, dom=dom, selector=sel), None, None

        popup_timeout = min(5000, int(default_timeout_ms))
        clicked = False
        try:
            with page.expect_popup(timeout=popup_timeout) as popup_info:
                loc.click(timeout=default_timeout_ms)
            popup = popup_info.value
            try:
                popup.wait_for_load_state("domcontentloaded", timeout=int(default_timeout_ms))
            except Exception:  # noqa: BLE001
                pass
            page = popup
            clicked = True
        except PlaywrightTimeoutError:
            pass
        if not clicked:
            loc.click(timeout=default_timeout_ms)
        if role_l == "combobox" and not clicked:
            for menu_sel in ('[role="listbox"]', '[role="menu"]'):
                try:
                    page.locator(menu_sel).first.wait_for(state="visible", timeout=2500)
                    break
                except Exception:  # noqa: BLE001
                    continue
        handle.dispose()
        _post_click_settle(page)
        desc = _planner_description(action, f"Click {dom.get('tag', 'element')}")
        return True, PlaybookStep(op="click", description=desc, dom=dom, selector=sel), None, None

    if op == "fill":
        ref, ref_err = _parse_ref(action, op="fill")
        if ref_err or ref is None:
            return True, None, ref_err, None
        value = action.get("value")
        if not isinstance(value, str):
            return True, None, "fill.value must be string", None
        clear_first = bool(action.get("clear_first", True))
        loc = _ref_locator(page, ref).first
        loc.scroll_into_view_if_needed(timeout=int(default_timeout_ms))
        handle = loc.element_handle()
        if handle is None:
            return True, None, f"fill: no element for ref {ref}", None
        sel = css_path_for_element(handle)
        dom = dom_fields_for_element(handle, selector=sel)
        is_select = bool(handle.evaluate("(el) => el instanceof HTMLSelectElement"))
        if not is_select:
            fillable = bool(
                handle.evaluate(
                    "(el) => el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement "
                    "|| (el instanceof HTMLElement && el.isContentEditable)"
                )
            )
            role_l = str(dom.get("role", "")).lower()
            if role_l == "combobox" or not fillable:
                handle.dispose()
                if role_l == "combobox":
                    return True, None, (
                        f"fill: ref {ref} is role=combobox — click to open the list, then pick_option with the "
                        "exact visible option text (e.g. month name in the page language), or use the day/year "
                        "text input ref from the snapshot list."
                    ), None
                return True, None, (
                    f"fill: ref {ref} (tag={dom.get('tag', 'element')!r}) is not a fillable text control — "
                    "use click, pick_option, or a different ref."
                ), None
        handle.dispose()
        expanded, gerr = try_expand_fill(value, dom=dom)
        if gerr:
            return True, None, gerr, None
        value = expanded
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
            ), None, None
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
                    None,
                )
        dom["entered_text"] = value
        try:
            if clear_first:
                loc.fill("")
            loc.fill(value, timeout=default_timeout_ms)
        except Exception as exc:  # noqa: BLE001 — Playwright fill errors become planner-visible strings
            return True, None, f"fill: ref {ref} failed: {exc}", None
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
        ), None, None

    if op == "press":
        key = action.get("key")
        if not isinstance(key, str) or not key.strip():
            return True, None, "press.key must be non-empty string", None
        k = key.strip()
        ref_raw = action.get("ref")
        sel: str | None = None
        dom: dict[str, Any] | None = None
        if ref_raw is not None:
            ref, ref_err = _parse_ref(action, op="press")
            if ref_err or ref is None:
                return True, None, ref_err, None
            loc = _ref_locator(page, ref).first
            loc.scroll_into_view_if_needed(timeout=int(default_timeout_ms))
            handle = loc.element_handle()
            if handle is None:
                return True, None, f"press: no element for ref {ref}", None
            sel = css_path_for_element(handle)
            dom = dom_fields_for_element(handle, selector=sel)
            loc.click(timeout=default_timeout_ms)
            handle.dispose()
            _post_click_settle(page)
        desc = _planner_description(action, f"Press keyboard key {k!r}")
        if dom is None:
            dom = {"key": k}
        else:
            dom = {**dom, "key": k}
        return True, PlaybookStep(op="press", description=desc, dom=dom, key=k, selector=sel), None, None

    return True, None, f"unknown op: {op}", None


def run_planner_action(
    page: Page,
    action: dict[str, Any],
    *,
    default_timeout_ms: float = 12_000,
    vision_png_path: Path | None = None,
) -> tuple[bool, PlaybookStep | None, str | None, dict[str, Any] | None]:
    """Execute one planner *action* dict.

    Returns:
        (continue_loop, playbook_step_recorded, error_message, optional_step_metadata)
    """
    try:
        return _run_planner_action_inner(
            page, action, default_timeout_ms=default_timeout_ms, vision_png_path=vision_png_path
        )
    except PlaywrightTimeoutError as exc:
        op = action.get("op", "?")
        ref = action.get("ref", "?")
        return True, None, f"{op}: Playwright timeout for ref {ref} — element may be stale, hidden, or detached. {exc}", None
    except (PageClosed, TargetClosedError) as exc:
        op = action.get("op", "?")
        return True, None, f"{op}: browser tab or session closed during step ({exc})", None
    except Exception as exc:  # noqa: BLE001
        op = action.get("op", "?")
        return True, None, f"{op}: unexpected executor error: {exc}", None


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
        if step.selector:
            try:
                page.locator(step.selector).first.click(timeout=int(default_timeout_ms))
                page.wait_for_timeout(400)
                _wait_for_dropdown_surface(page, timeout_ms=int(default_timeout_ms))
            except Exception:  # noqa: BLE001
                pass
        err = _pick_role_option(page, step.value, timeout_ms=int(default_timeout_ms))
        if err:
            for variant in _label_pick_variants(step.value):
                err = _pick_role_option(page, variant, timeout_ms=int(default_timeout_ms))
                if err is None:
                    break
                err = _click_visible_text_option(page, variant, timeout_ms=int(default_timeout_ms))
                if err is None:
                    break
        if err:
            raise RuntimeError(err)
        _post_click_settle(page)
        return
    if step.op in ("click", "fill", "scroll_into_view"):
        if not step.selector:
            raise ValueError(f"{step.op} step missing selector")
        loc = page.locator(step.selector).first
        loc.scroll_into_view_if_needed(timeout=int(default_timeout_ms))
        if step.op == "click":
            loc.click(timeout=default_timeout_ms)
            _post_click_settle(page)
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
            _post_click_settle(page)
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
