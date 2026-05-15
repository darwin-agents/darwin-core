from __future__ import annotations

from darwin_core.agents.web.playbook.playbook import PlaybookStep
from darwin_core.agents.web.integrations.email_providers import EmailProvider
from darwin_core.agents.web.playbook.playbook_record import (
    is_duplicate_playbook_step,
    sanitize_playbook_step,
    should_record_playbook_step,
)

_MAILFENCE = EmailProvider("Mailfence", "BE", "https://mailfence.com", "Low", "")


def test_skip_scripted_auto_advance() -> None:
    assert not should_record_playbook_step(
        action={
            "op": "goto",
            "url": "https://www.inbox.lv",
            "describe": "auto-advance: next ranked email provider (stagnation)",
        },
        tag="scripted",
        executor_error=None,
        stagnation=False,
        locked_provider=_MAILFENCE,
        recorded=[],
    )


def test_skip_goto_other_provider_when_locked() -> None:
    assert not should_record_playbook_step(
        action={"op": "goto", "url": "https://www.inbox.lv", "describe": "try inbox"},
        tag="planner",
        executor_error=None,
        stagnation=False,
        locked_provider=_MAILFENCE,
        recorded=[],
    )


def test_skip_stagnation_and_reflect() -> None:
    assert not should_record_playbook_step(
        action={"op": "click", "ref": 1, "describe": "x"},
        tag="reflect",
        executor_error=None,
        stagnation=False,
        locked_provider=_MAILFENCE,
        recorded=[],
    )
    assert not should_record_playbook_step(
        action={"op": "click", "ref": 1, "describe": "x"},
        tag="planner",
        executor_error=None,
        stagnation=True,
        locked_provider=_MAILFENCE,
        recorded=[],
    )


def test_sanitize_password_and_username() -> None:
    step = PlaybookStep(
        op="fill",
        description="password",
        dom={"type": "password", "entered_text": "U4D3qqKK%L7y2M928SGXd9C3"},
        selector="#pw",
        value="U4D3qqKK%L7y2M928SGXd9C3",
    )
    out = sanitize_playbook_step(step, action={"op": "fill"})
    assert out.value == "$GENHASH_PW"
    assert out.dom is not None
    assert out.dom["entered_text"] == "$GENHASH_PW"

    user = PlaybookStep(
        op="fill",
        description="user",
        dom={"name": "login", "placeholder": "Nombre de usuario", "entered_text": "f2exvp7o67"},
        selector="input",
        value="f2exvp7o67",
    )
    out2 = sanitize_playbook_step(user, action={"op": "fill"})
    assert out2.value == "$GENHASH"


def test_dedupe_consecutive_fill() -> None:
    a = PlaybookStep(op="fill", description="a", selector="s", value="Alex")
    b = PlaybookStep(op="fill", description="b", selector="s", value="Alex")
    assert is_duplicate_playbook_step(a, b)
