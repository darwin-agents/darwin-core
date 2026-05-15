"""Language-neutral planner hints derived from observation + recent actions (no site-specific URLs)."""

from __future__ import annotations

from collections import deque
from typing import Any
from urllib.parse import urlparse

from darwin_web.genhash import reserved_email_domain_error


def listbox_open_hint(items: list[dict[str, Any]]) -> str:
    """When option rows are visible, steer toward pick_option instead of re-clicking the trigger."""
    if not any(str(i.get("role", "")).lower() in ("option", "menuitem") for i in items):
        return ""
    return (
        '\nNOTE: A dropdown menu is visible (elements with role "option" or "menuitem"). '
        'Use {"op":"pick_option","label":"<exact visible row text>"} or click that option ref. '
        "Do not click the combobox trigger again while the menu is open.\n"
    )


def stuck_repeated_click_hint(
    recent: deque[tuple[str, int | None, str | None]],
) -> str:
    """Same ref clicked several times without progress."""
    if len(recent) < 3:
        return ""
    last_three = list(recent)[-3:]
    if not all(op == "click" for op, _r, _d in last_three):
        return ""
    refs = [r for _op, r, _d in last_three]
    if refs[0] is None or refs[0] != refs[1] or refs[1] != refs[2]:
        return ""
    return (
        f"\nNOTE: You clicked ref {refs[0]} three times in a row with no URL/fingerprint change. "
        "Opening the control is not enough: use combobox_pick with the combobox ref and label from "
        "OWNER_PROFILE (one action opens and selects). Do not click the same combobox ref again.\n"
    )


def stuck_repeated_fill_hint(
    recent: deque[tuple[str, int | None, str | None]],
) -> str:
    """Same ref filled several times — often $GENHASH loops while the form is already valid."""
    if len(recent) < 3:
        return ""
    last_three = list(recent)[-3:]
    if not all(op == "fill" for op, _r, _d in last_three):
        return ""
    refs = [r for _op, r, _d in last_three]
    if refs[0] is None or refs[0] != refs[1] or refs[1] != refs[2]:
        return ""
    return (
        f"\nNOTE: You used fill on ref {refs[0]} three times in a row without leaving this screen. "
        "The control likely already has an acceptable value — click the form submit/primary button "
        "or address a visible validation error instead of fill with $GENHASH again.\n"
    )


def _is_domain_selector_combobox(it: dict[str, Any]) -> bool:
    """Combobox whose visible text/value looks like an email domain (``@host`` or ``host.tld``)."""
    if str(it.get("role", "")).lower() != "combobox":
        return False
    text = str(it.get("text", "")).strip()
    if text.startswith("@"):
        return True
    val = str(it.get("value", "")).strip().lower()
    return bool(val) and "." in val and " " not in val


def _is_local_part_text_input(it: dict[str, Any]) -> bool:
    """Text/email input that holds a local part (no ``@`` in the current value)."""
    if str(it.get("tag", "")).lower() != "input":
        return False
    typ = str(it.get("type", "")).lower()
    if typ not in ("", "text", "email"):
        return False
    val = str(it.get("value", "")).strip()
    return bool(val) and "@" not in val


def _is_form_submit_button(it: dict[str, Any]) -> bool:
    if str(it.get("tag", "")).lower() != "button":
        return False
    if str(it.get("role", "")).lower() == "combobox":
        return False
    return str(it.get("type", "")).lower() == "submit"


def _signup_mail_hosts_from_page_url(url: str) -> tuple[str, ...]:
    """Hostname heuristics for signup pages with a single full-email field (no domain combobox yet)."""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return ()
    for prefix in ("signup.", "account.", "accounts.", "register.", "id.", "login."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    if host.endswith("live.com") or host.endswith("microsoft.com") or "outlook" in host:
        return ("hotmail.com", "outlook.com")
    if "yahoo" in host:
        return ("yahoo.com",)
    if "proton" in host:
        return ("proton.me", "protonmail.com")
    if "zoho" in host:
        return ("zoho.com",)
    return ()


def full_email_field_domain_hint(*, url: str, items: list[dict[str, Any]]) -> str:
    """Single ``type=email`` field without a domain combobox — steer away from example.com."""
    if any(_is_domain_selector_combobox(it) for it in items):
        return ""
    if not any(str(it.get("type", "")).lower() == "email" for it in items):
        return ""
    for it in items:
        val = str(it.get("value", "")).strip()
        if val and reserved_email_domain_error(val):
            hosts = _signup_mail_hosts_from_page_url(url)
            if hosts:
                return (
                    f"\nNOTE: Reserved/documentation domains are rejected. Use `$GENHASH@{hosts[0]}` "
                    f"(or {', '.join(hosts[1:])} if offered) — not example.com.\n"
                )
            return (
                "\nNOTE: Reserved/documentation domains are rejected. Use `$GENHASH@<real-provider-domain>` "
                "from this signup (never example.com or test.com).\n"
            )
    hosts = _signup_mail_hosts_from_page_url(url)
    if not hosts:
        return ""
    return (
        f"\nNOTE: Full-email signup field — use `$GENHASH@{hosts[0]}` "
        f"(provider domains commonly used here: {', '.join(hosts)}). "
        "Never example.com, test.com, or localhost.\n"
    )


def split_local_part_and_domain_ready_hint(items: list[dict[str, Any]]) -> str:
    """Local-part text field + ``@`` domain combobox + submit — advance via click, not refill."""
    domain_refs: list[int] = []
    submit_refs: list[int] = []
    local_ref: int | None = None
    for it in items:
        ref = it.get("ref")
        if ref is None:
            continue
        try:
            ref_i = int(ref)
        except (TypeError, ValueError):
            continue
        if _is_domain_selector_combobox(it):
            if str(it.get("text", "")).strip() or str(it.get("value", "")).strip():
                domain_refs.append(ref_i)
        elif _is_local_part_text_input(it):
            local_ref = ref_i
        elif _is_form_submit_button(it):
            submit_refs.append(ref_i)

    if local_ref is None or not domain_refs or not submit_refs:
        return ""
    submit_ref = min(submit_refs)
    domain_ref = domain_refs[0]
    return (
        f"\nNOTE: This screen splits address entry: text field ref {local_ref} (local part only) "
        f"and domain combobox ref {domain_ref}. Do not type ``@`` or the domain into the text field. "
        f"When both parts look set, click submit ref {submit_ref} — do not regenerate ``$GENHASH`` "
        "for the text field unless validation errors name that field.\n"
    )


def combobox_empty_with_validation_hint(
    items: list[dict[str, Any]],
    alert_digest: str,
    owner_profile: dict[str, str],
) -> str:
    """Birth-date style forms: empty day/month comboboxes + validation text."""
    alert_l = alert_digest.lower()
    if not any(
        phrase in alert_l
        for phrase in (
            "fecha de nacimiento",
            "date of birth",
            "birth date",
            "birthday",
            "fecha de nac",
        )
    ):
        return ""
    unset = [
        it
        for it in items
        if str(it.get("role", "")).lower() == "combobox"
        and not str(it.get("text", "")).strip()
        and not str(it.get("value", "")).strip()
    ]
    if len(unset) < 1:
        return ""
    day = owner_profile.get("birth_day", "").strip()
    month = owner_profile.get("birth_month", "").strip()
    parts = []
    if day:
        parts.append(f'day "{day}"')
    if month:
        parts.append(f'month "{month}" (use localized spelling if the menu is not English)')
    if not parts:
        return (
            "\nNOTE: Validation asks for a complete birth date. For each empty combobox: "
            "click once to open, then pick_option with the visible row text.\n"
        )
    return (
        "\nNOTE: Validation asks for a complete birth date. For each empty day/month combobox: "
        f"use combobox_pick on each empty combobox ref with {', '.join(parts)}. "
        "Do not click Siguiente/Next until all parts are set.\n"
    )


def pick_option_error_hint(errors: list[str]) -> str:
    """Recover from reflect/planner pick_option mistakes."""
    tail = " ".join(errors[-4:]).lower()
    if "pick_option requires label" in tail:
        return (
            '\nNOTE: pick_option MUST include "label" with the exact visible menu row text '
            "(e.g. birth_day from OWNER_PROFILE for day, birth_month for month).\n"
        )
    if "no visible role=option" in tail or "no visible role=menuitem" in tail:
        return (
            "\nNOTE: pick_option failed because menu rows were not visible to automation. "
            "Click the combobox ref once, use wait_ms 400, then pick_option with the label text "
            "or click the option ref from the updated element list.\n"
        )
    return ""


def build_planner_hints(
    *,
    page_url: str,
    items: list[dict[str, Any]],
    alert_digest: str,
    owner_profile: dict[str, str],
    recent_actions: deque[tuple[str, int | None, str | None]],
    errors: list[str],
) -> str:
    """Concatenate all applicable generic hints for one planner turn."""
    chunks = [
        listbox_open_hint(items),
        stuck_repeated_click_hint(recent_actions),
        stuck_repeated_fill_hint(recent_actions),
        full_email_field_domain_hint(url=page_url, items=items),
        split_local_part_and_domain_ready_hint(items),
        combobox_empty_with_validation_hint(items, alert_digest, owner_profile),
        pick_option_error_hint(errors),
    ]
    return "".join(c for c in chunks if c)
