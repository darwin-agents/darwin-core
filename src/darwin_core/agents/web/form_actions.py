from __future__ import annotations

from typing import Any

from .prompts import GENDER_OPTIONS, MONTH_NAMES
from .web_owner_profile import WebOwnerProfile


def infer_field_kind(control: dict[str, Any]) -> str:
    joined = " ".join(
        str(control.get(key, "") or "")
        for key in ("name", "id", "labelText", "ariaLabel", "placeholder", "type", "text")
    ).lower()
    if "email" in joined:
        return "email"
    if "password" in joined:
        return "password"
    if "first" in joined and "name" in joined:
        return "first_name"
    if "last" in joined and "name" in joined:
        return "last_name"
    if "phone" in joined or "mobile" in joined:
        return "phone"
    if "month" in joined:
        return "month"
    if "day" in joined:
        return "day"
    if "year" in joined:
        return "year"
    if "gender" in joined or "sex" in joined:
        return "gender"
    return "generic_text"


def value_for_field(field_kind: str, profile: WebOwnerProfile) -> str:
    """Resolve the string to use for a given inferred field kind from the owner's profile."""
    by_kind: dict[str, str] = {
        "email": profile.email,
        "password": profile.password,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "phone": profile.phone,
        "day": profile.birth_day,
        "year": profile.birth_year,
        "month": profile.birth_month,
        "gender": profile.gender,
        "generic_text": profile.generic_text,
    }
    return by_kind.get(field_kind, profile.generic_text)


def is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return True
        if normalized in {"month", "day", "year", "gender", "select", "choose"}:
            return True
        return False
    return False


def should_fill_control(control: dict[str, Any]) -> bool:
    if control.get("disabled") or not control.get("visible"):
        return False
    required = bool(control.get("required"))
    kind = infer_field_kind(control)
    likely_signup_field = kind in {"first_name", "last_name", "email", "password", "month", "day", "year", "gender"}
    current_value = control.get("value")
    if is_empty_value(current_value):
        current_value = control.get("text")
    return is_empty_value(current_value) and (required or likely_signup_field)


def action_for_control(control: dict[str, Any], profile: WebOwnerProfile) -> list[dict[str, Any]]:
    selector = control.get("selectorHint")
    if not isinstance(selector, str) or not selector:
        return []
    field_kind = infer_field_kind(control)
    text_value = value_for_field(field_kind, profile)
    tag = str(control.get("tag", ""))
    role = str(control.get("role", ""))

    if tag == "select":
        options = control.get("options")
        if isinstance(options, list):
            chosen = None
            for option in options:
                value = str(option.get("value", "")).strip()
                text = str(option.get("text", "")).strip()
                if not value:
                    continue
                if text.lower() in {"month", "day", "year", "gender", "select"}:
                    continue
                if field_kind == "month" and text_value.lower() in text.lower():
                    chosen = value
                    break
                if field_kind == "gender":
                    tv = text_value.lower()
                    tl = text.lower()
                    if tv and (tv in tl or tl in tv):
                        chosen = value
                        break
                if chosen is None:
                    chosen = value
            if chosen:
                return [
                    {
                        "action": "select_option",
                        "selector": selector,
                        "value": chosen,
                        "key": None,
                        "target_text": None,
                        "text": None,
                        "url": None,
                        "wait_ms": None,
                        "reason": f"Auto-fill select field ({field_kind}).",
                    }
                ]
    if role == "combobox":
        return [
            {
                "action": "click",
                "selector": selector,
                "value": None,
                "key": None,
                "target_text": None,
                "text": None,
                "url": None,
                "wait_ms": None,
                "reason": f"Auto-open combobox ({field_kind}).",
            },
            {
                "action": "wait",
                "selector": None,
                "value": None,
                "key": None,
                "target_text": None,
                "text": None,
                "url": None,
                "wait_ms": 800,
                "reason": f"Wait for combobox list to render ({field_kind}).",
            },
            {
                "action": "click_text",
                "selector": None,
                "value": None,
                "key": None,
                "target_text": text_value,
                "text": None,
                "url": None,
                "wait_ms": None,
                "reason": f"Auto-select combobox option by visible text ({field_kind}).",
            },
        ]

    input_type = str(control.get("type", "text")).lower()
    if input_type in {"checkbox", "radio", "file", "hidden", "submit", "button"}:
        return []
    return [
        {
            "action": "type",
            "selector": selector,
            "value": text_value,
            "key": None,
            "target_text": None,
            "text": text_value,
            "url": None,
            "wait_ms": None,
            "reason": f"Auto-fill input field ({field_kind}).",
        }
    ]


def choose_form_actions(snapshot: dict[str, Any], profile: WebOwnerProfile) -> list[dict[str, Any]]:
    controls = snapshot.get("form_controls")
    if not isinstance(controls, list):
        return []
    for raw_control in controls:
        if not isinstance(raw_control, dict):
            continue
        if not should_fill_control(raw_control):
            continue
        candidate_actions = action_for_control(raw_control, profile)
        if candidate_actions:
            return candidate_actions
    return []


def google_birthday_ready_to_continue(snapshot: dict[str, Any]) -> bool:
    url = str(snapshot.get("url", ""))
    if "accounts.google.com/lifecycle/steps/signup/birthdaygender" not in url:
        return False

    day_value = ""
    year_value = ""
    month_filled = False
    gender_filled = False
    month_tokens = tuple(name.lower() for name in MONTH_NAMES)
    gender_tokens = tuple(name.lower() for name in GENDER_OPTIONS)

    form_controls = snapshot.get("form_controls")
    if isinstance(form_controls, list):
        for control in form_controls:
            if not isinstance(control, dict):
                continue
            if not control.get("visible", True):
                continue
            joined = " ".join(
                str(control.get(key, "") or "")
                for key in ("name", "id", "labelText", "ariaLabel", "placeholder", "text")
            ).lower()
            value_text = str(control.get("value", "") or control.get("text", "") or "").strip()

            if "day" in joined and len(value_text) >= 1:
                day_value = value_text
            elif "year" in joined and len(value_text) >= 4:
                year_value = value_text
            elif "month" in joined:
                lowered = value_text.lower()
                month_filled = any(token in lowered for token in month_tokens)
            elif "gender" in joined:
                lowered = value_text.lower()
                gender_filled = any(token in lowered for token in gender_tokens)

    interactive_controls = snapshot.get("interactive_controls")
    if isinstance(interactive_controls, list):
        for control in interactive_controls:
            if not isinstance(control, dict):
                continue
            role = str(control.get("role", "") or "").lower()
            tag = str(control.get("tag", "") or "").lower()
            joined = " ".join(
                str(control.get(key, "") or "")
                for key in ("name", "id", "ariaLabel", "text", "placeholder")
            ).lower()
            value_text = str(control.get("value", "") or control.get("text", "") or "").strip()

            if not month_filled and "month" in joined and role == "combobox":
                lowered = value_text.lower()
                month_filled = any(token in lowered for token in month_tokens)
            if not gender_filled and "gender" in joined and role == "combobox":
                lowered = value_text.lower()
                gender_filled = any(token in lowered for token in gender_tokens)
            if not day_value and "day" in joined and tag == "input" and len(value_text) >= 1:
                day_value = value_text
            if not year_value and "year" in joined and tag == "input" and len(value_text) >= 4:
                year_value = value_text

    return bool(day_value) and len(year_value) >= 4 and month_filled and gender_filled

