from __future__ import annotations

from darwin_core.agents.web.intelligence.human_wall import (
    build_captcha_request_human_action,
    detect_captcha_wall,
    explain_why_not_automated,
)


def test_explain_captcha_iframe_wall() -> None:
    items = [
        {"ref": 1, "tag": "button", "type": "button", "id": "back-button", "text": "", "value": ""},
    ]
    why = explain_why_not_automated(
        title="Prove you are human",
        alert_digest="Prove you are human",
        items=items,
        aria_snapshot="- main:\n  - iframe\n",
        form_html='<motion.div id="human" data-testid="humanCaptchaDescription">',
    )
    assert "iframe" in why.lower()
    assert "press-and-hold" in why.lower() or "human-verification" in why.lower()


def test_detect_captcha_wall_outlook_style() -> None:
    items = [
        {"ref": 1, "tag": "button", "type": "button", "id": "back-button", "text": "", "value": ""},
    ]
    assert detect_captcha_wall(
        title="Let's prove you're human",
        alert_digest="",
        items=items,
        aria_snapshot="- main:\n  - iframe\n",
        form_html='<div data-testid="humanCaptchaDescription">press and hold</motion.div>',
    )


def test_detect_captcha_wall_false_when_submit_present_without_iframe() -> None:
    items = [
        {
            "ref": 2,
            "tag": "button",
            "type": "submit",
            "text": "Continue",
            "aria": "",
            "role": "",
        },
    ]
    assert not detect_captcha_wall(
        title="Sign up",
        alert_digest="",
        items=items,
        aria_snapshot="",
        form_html="",
    )


def test_build_captcha_request_human_action() -> None:
    action = build_captcha_request_human_action(
        title="Prove you are human",
        alert_digest="",
        items=[],
        aria_snapshot="- iframe\n",
        form_html="captcha",
    )
    assert action["op"] == "request_human"
    assert "live browser" in action["instructions"].lower()
    assert "iframe" in action["instructions"].lower()


def test_explain_includes_executor_error_head() -> None:
    why = explain_why_not_automated(
        title="T",
        alert_digest="",
        items=[],
        aria_snapshot="",
        executor_error="click: Playwright timeout for ref 7",
    )
    assert "timeout" in why.lower()
