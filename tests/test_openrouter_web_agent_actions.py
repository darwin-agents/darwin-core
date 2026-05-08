from __future__ import annotations

import pytest

from darwin_core.agents.web.agent import choose_form_actions, run_action


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
    actions = choose_form_actions(snapshot)
    assert actions
    assert actions[0]["action"] == "type"
    assert actions[0]["selector"] == "#firstName"


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
    actions = choose_form_actions(snapshot)
    assert [item["action"] for item in actions] == ["click", "wait", "click_text"]
    assert actions[1]["wait_ms"] == 800
    assert actions[2]["target_text"] == "January"


def test_choose_form_actions_treats_month_placeholder_as_empty() -> None:
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
    actions = choose_form_actions(snapshot)
    assert actions
    assert actions[0]["selector"] == "#month"
