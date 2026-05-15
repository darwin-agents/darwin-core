from __future__ import annotations

from darwin_web2.human_wall import explain_why_not_automated


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


def test_explain_includes_executor_error_head() -> None:
    why = explain_why_not_automated(
        title="T",
        alert_digest="",
        items=[],
        aria_snapshot="",
        executor_error="click: Playwright timeout for ref 7",
    )
    assert "timeout" in why.lower()
