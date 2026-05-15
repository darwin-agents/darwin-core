from __future__ import annotations

from collections import deque

from darwin_core.agents.web.intelligence.hints import (
    build_planner_hints,
    combobox_empty_with_validation_hint,
    split_local_part_and_domain_ready_hint,
    stuck_repeated_click_hint,
    stuck_repeated_fill_hint,
)


def test_stuck_repeated_click_hint_triggers_on_three_same_clicks() -> None:
    tail: deque[tuple[str, int | None, str | None]] = deque(
        [
            ("click", 3, "open day"),
            ("click", 3, "open day again"),
            ("click", 3, "open day again 2"),
        ],
        maxlen=8,
    )
    hint = stuck_repeated_click_hint(tail)
    assert "ref 3" in hint
    assert "combobox_pick" in hint


def test_combobox_birth_date_hint_uses_owner_profile() -> None:
    items = [
        {"role": "combobox", "text": "", "value": "", "aria": "Día de nacimiento"},
        {"role": "combobox", "text": "", "value": "", "aria": "Mes de nacimiento"},
    ]
    hint = combobox_empty_with_validation_hint(
        items,
        "Escriba su fecha de nacimiento.",
        {"birth_day": "19", "birth_month": "December"},
    )
    assert "19" in hint
    assert "December" in hint
    assert "combobox_pick" in hint


def test_stuck_repeated_fill_hint_triggers_on_three_same_fills() -> None:
    tail: deque[tuple[str, int | None, str | None]] = deque(
        [
            ("fill", 1, "u1"),
            ("fill", 1, "u2"),
            ("fill", 1, "u3"),
        ],
        maxlen=8,
    )
    hint = stuck_repeated_fill_hint(tail)
    assert "ref 1" in hint
    assert "submit" in hint.lower()


def test_split_local_part_domain_hint_when_form_looks_complete() -> None:
    items = [
        {"ref": 1, "tag": "input", "type": "email", "role": "", "text": "", "value": "userabc"},
        {"ref": 2, "tag": "button", "role": "combobox", "type": "button", "text": "@mail.example", "value": "mail.example"},
        {"ref": 3, "tag": "button", "type": "submit", "role": "", "text": "Continue", "value": ""},
    ]
    hint = split_local_part_and_domain_ready_hint(items)
    assert "ref 1" in hint
    assert "ref 2" in hint
    assert "ref 3" in hint
    assert "$GENHASH" in hint


def test_full_email_hint_suggests_provider_domain_from_signup_host() -> None:
    items = [
        {"ref": 1, "tag": "input", "type": "email", "role": "", "text": "", "value": "x@example.com"},
        {"ref": 2, "tag": "button", "type": "submit", "role": "", "text": "Next", "value": ""},
    ]
    hint = build_planner_hints(
        page_url="https://signup.live.com/?lic=1",
        items=items,
        alert_digest="",
        owner_profile={},
        recent_actions=deque(),
        errors=[],
    )
    assert "hotmail.com" in hint
    assert "example.com" in hint


def test_build_planner_hints_includes_pick_option_error_recovery() -> None:
    hints = build_planner_hints(
        page_url="https://example.org",
        items=[],
        alert_digest="",
        owner_profile={},
        recent_actions=deque(),
        errors=["turn 5: pick_option requires label|text|value (non-empty string)"],
    )
    assert "pick_option MUST include" in hints
