from __future__ import annotations

from darwin_web.navigator import (
    _birthday_month_committed_hint,
    _coerce_planner_raw,
    _human_wall_page_hint,
    _listbox_open_hint,
    _stuck_fill_hint,
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
    assert "Day" in h


def test_birthday_month_committed_hint_empty_for_plain_month() -> None:
    items = [{"ref": 1, "role": "combobox", "text": "Month", "value": ""}]
    assert _birthday_month_committed_hint(items) == ""


def test_human_wall_page_hint_google_verify_title() -> None:
    h = _human_wall_page_hint("Verify some info before creating an account", "https://accounts.google.com/x")
    assert "request_human" in h


def test_human_wall_page_hint_empty() -> None:
    assert _human_wall_page_hint("Welcome", "https://example.com") == ""


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
