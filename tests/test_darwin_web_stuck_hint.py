from __future__ import annotations

from collections import deque

from darwin_web.navigator import (
    _birthday_month_committed_hint,
    _coerce_planner_raw,
    _consecutive_same_ref_fill_hint,
    _human_wall_page_hint,
    _listbox_open_hint,
    _stuck_fill_hint,
    _stuck_repeated_click_hint,
    _verification_code_field_hint,
)


def test_stuck_fill_hint_when_value_already_matches() -> None:
    items = [{"ref": 1, "tag": "input", "value": "John"}]
    last = {"op": "fill", "ref": 1, "value": "John", "describe": "x"}
    hint = _stuck_fill_hint(items, last)
    assert "STUCK-PREVENTION" in hint
    assert "Do NOT fill" in hint


def test_stuck_fill_hint_noop_when_different_value() -> None:
    items = [{"ref": 1, "tag": "input", "value": ""}]
    last = {"op": "fill", "ref": 1, "value": "John", "describe": "x"}
    assert _stuck_fill_hint(items, last) == ""


def test_repeated_click_hint_after_three_identical_clicks() -> None:
    tail = deque(
        [
            ("fill", 1, "x"),
            ("click", 2, None),
            ("click", 2, None),
            ("click", 2, None),
        ],
        maxlen=8,
    )
    h = _stuck_repeated_click_hint(tail)
    assert "STUCK-PREVENTION" in h
    assert "ref 2" in h


def test_repeated_click_hint_empty_for_mixed_last_three() -> None:
    tail = deque([("click", 2, None), ("fill", 1, None), ("click", 2, None)], maxlen=8)
    assert _stuck_repeated_click_hint(tail) == ""


def test_listbox_open_hint_when_option_rows_present() -> None:
    items = [{"ref": 1, "role": "combobox"}, {"ref": 2, "role": "option", "text": "January"}]
    h = _listbox_open_hint(items)
    assert "pick_option" in h
    assert "January" in h


def test_listbox_open_hint_empty_without_options() -> None:
    assert _listbox_open_hint([{"ref": 1, "role": "combobox"}]) == ""


def test_birthday_month_committed_hint_when_month_in_text() -> None:
    items = [{"ref": 1, "role": "combobox", "text": "Month January", "value": ""}]
    h = _birthday_month_committed_hint(items)
    assert "ALREADY selected" in h
    assert "gender" in h.lower() or "género" in h.lower()


def test_birthday_month_committed_hint_when_month_in_text_spanish() -> None:
    items = [{"ref": 1, "role": "combobox", "text": "Mes Enero", "value": ""}]
    h = _birthday_month_committed_hint(items)
    assert "Mes Enero" in h or "mes" in h.lower()
    assert "gender" in h.lower() or "género" in h.lower()


def test_birthday_month_committed_hint_empty_for_plain_month() -> None:
    items = [{"ref": 1, "role": "combobox", "text": "Month", "value": ""}]
    assert _birthday_month_committed_hint(items) == ""


def test_human_wall_page_hint_spanish_email_verify_title() -> None:
    h = _human_wall_page_hint("Verificar tu dirección de correo electrónico", "https://accounts.google.com/")
    assert "request_human" in h
    assert "code" in h.lower() or "verification" in h.lower() or "inbox" in h.lower()


def test_human_wall_page_hint_google_verify_title() -> None:
    h = _human_wall_page_hint("Verify some info before creating an account", "https://accounts.google.com/x")
    assert "request_human" in h


def test_human_wall_page_hint_empty() -> None:
    assert _human_wall_page_hint("Welcome", "https://example.com") == ""


def test_verification_code_field_hint_from_placeholder() -> None:
    items = [
        {
            "ref": 3,
            "tag": "input",
            "type": "text",
            "aria": "",
            "placeholder": "Introduce el código",
            "name": "",
            "id": "",
            "text": "",
        }
    ]
    h = _verification_code_field_hint(items, "Google")
    assert "AUTONOMY" in h
    assert "request_human" in h


def test_verification_code_field_hint_empty() -> None:
    items = [{"ref": 1, "tag": "input", "type": "text", "placeholder": "Email", "aria": ""}]
    assert _verification_code_field_hint(items, "Sign in") == ""


def test_consecutive_same_ref_fill_hint() -> None:
    tail = deque(
        [("fill", 5, "a"), ("fill", 5, "b"), ("fill", 5, "c")],
        maxlen=8,
    )
    h = _consecutive_same_ref_fill_hint(tail)
    assert "AUTONOMY" in h
    assert "ref 5" in h
    assert "3+" in h


def test_consecutive_same_ref_fill_hint_two_fills_no_triple_extra() -> None:
    tail = deque([("fill", 5, "a"), ("fill", 5, "b")], maxlen=8)
    h = _consecutive_same_ref_fill_hint(tail)
    assert "AUTONOMY" in h
    assert "3+" not in h


def test_consecutive_same_ref_fill_hint_requires_two() -> None:
    tail = deque([("fill", 5, "a")], maxlen=8)
    assert _consecutive_same_ref_fill_hint(tail) == ""


def test_coerce_nested_action_under_fill_key() -> None:
    raw: dict = {
        "thought": "t",
        "action": {
            "fill": {
                "op": "fill",
                "ref": 1,
                "value": "x",
                "clear_first": True,
                "describe": "d",
            }
        },
    }
    _coerce_planner_raw(raw)
    assert raw["action"]["op"] == "fill"
    assert raw["action"]["ref"] == 1
