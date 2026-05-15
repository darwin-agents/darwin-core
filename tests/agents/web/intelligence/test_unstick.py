from __future__ import annotations

from darwin_core.agents.web.intelligence.unstick import build_signup_unstick_actions, is_registration_url


def test_is_registration_url() -> None:
    assert is_registration_url("https://mailfence.com/registration/")
    assert not is_registration_url("https://mailfence.com/inbox/")


def test_unstick_checks_then_submit() -> None:
    items = [
        {"ref": 1, "tag": "input", "type": "checkbox", "checked": "false"},
        {"ref": 2, "tag": "input", "type": "checkbox", "checked": "false"},
        {"ref": 3, "tag": "a", "type": "", "text": "Registrarse", "aria": ""},
    ]
    actions = build_signup_unstick_actions(items)
    assert len(actions) == 3
    assert actions[0]["op"] == "click" and actions[0]["ref"] == 1
    assert actions[2]["ref"] == 3
