from __future__ import annotations

import pytest

from darwin_core.agents.web.agent import choose_form_actions, run_action
from darwin_core.agents.web.web_owner_profile import WebOwnerProfile, load_web_owner_profile


def _test_owner_profile() -> WebOwnerProfile:
    return WebOwnerProfile.from_dict(
        {
            "email": "owner@example.com",
            "password": "s3cret!",
            "first_name": "John",
            "last_name": "Doe",
            "phone": "2025550142",
            "birth_day": "15",
            "birth_month": "January",
            "birth_year": "1998",
            "gender": "Male",
        }
    )


class _Locator:
    def __init__(self) -> None:
        self.filled: str | None = None

    @property
    def first(self) -> "_Locator":
        return self

    def fill(self, value: str, timeout: int) -> None:  # noqa: ARG002
        self.filled = value


class _Page:
    def __init__(self) -> None:
        self.loc = _Locator()

    def locator(self, selector: str) -> _Locator:  # noqa: ARG002
        return self.loc


def test_type_action_uses_value_when_text_absent() -> None:
    page = _Page()
    action = {"action": "type", "selector": "#firstName", "value": "John", "text": None}
    should_continue = run_action(page, action)
    assert should_continue is True
    assert page.loc.filled == "John"


def test_type_action_requires_value_or_text() -> None:
    page = _Page()
    action = {"action": "type", "selector": "#firstName", "value": None, "text": None}
    with pytest.raises(RuntimeError, match="type action missing text/value"):
        run_action(page, action)


def test_choose_form_actions_prefers_required_empty_input() -> None:
    snapshot = {
        "form_controls": [
            {
                "tag": "input",
                "role": None,
                "name": "firstName",
                "id": "firstName",
                "required": True,
                "disabled": False,
                "visible": True,
                "value": "",
                "selectorHint": "#firstName",
                "labelText": "First name",
                "ariaLabel": None,
                "placeholder": None,
            }
        ]
    }
    actions = choose_form_actions(snapshot, _test_owner_profile())
    assert actions
    assert actions[0]["action"] == "type"
    assert actions[0]["selector"] == "#firstName"
    assert actions[0]["value"] == "John"


def test_choose_form_actions_builds_combobox_sequence() -> None:
    snapshot = {
        "form_controls": [
            {
                "tag": "div",
                "role": "combobox",
                "name": "month",
                "id": "month",
                "required": True,
                "disabled": False,
                "visible": True,
                "value": "",
                "selectorHint": "#month",
                "labelText": "Month",
                "ariaLabel": "Month",
                "placeholder": "Month",
            }
        ]
    }
    actions = choose_form_actions(snapshot, _test_owner_profile())
    assert [item["action"] for item in actions] == ["click", "wait", "click_text"]
    assert actions[1]["wait_ms"] == 800
    assert actions[2]["target_text"] == "January"


def test_load_web_owner_profile_rejects_empty_field(tmp_path) -> None:
    path = tmp_path / "owner.json"
    path.write_text('{"email": "a@b.co", "password": "x"}', encoding="utf-8")
    with pytest.raises(ValueError, match="missing or empty"):
        load_web_owner_profile(path)
    snapshot = {
        "form_controls": [
            {
                "tag": "div",
                "role": "combobox",
                "name": "month",
                "id": "month",
                "required": True,
                "disabled": False,
                "visible": True,
                "value": "Month",
                "selectorHint": "#month",
                "labelText": "Month",
                "ariaLabel": "Month",
                "placeholder": "Month",
            }
        ]
    }
    actions = choose_form_actions(snapshot, _test_owner_profile())
    assert actions
    assert actions[0]["selector"] == "#month"
