"""Language-neutral explanations when automation cannot complete a verification wall."""

from __future__ import annotations

from typing import Any

from darwin_core.agents.web.intelligence.unstick import _is_submit_like

_CAPTCHA_MARKERS = (
    "captcha",
    "press and hold",
    "press-and-hold",
    "human verification",
    "prove you're human",
    "prove you are human",
    "verify you are human",
    "security check",
)


def detect_captcha_wall(
    *,
    title: str,
    alert_digest: str,
    items: list[dict[str, Any]],
    aria_snapshot: str,
    form_html: str = "",
) -> bool:
    """True when the page looks like an iframe CAPTCHA / press-and-hold wall (Outlook-style)."""
    aria_l = (aria_snapshot or "").lower()
    html_l = (form_html or "").lower()
    blob = f"{title} {alert_digest} {aria_l} {html_l}".lower()
    has_iframe = "iframe" in aria_l or "<iframe" in html_l
    has_marker = any(m in blob for m in _CAPTCHA_MARKERS)
    if not has_marker:
        return False
    if not has_iframe:
        # Strong title-only walls without iframe in a11y tree
        title_l = (title or "").lower()
        if not any(m in title_l or m in (alert_digest or "").lower() for m in _CAPTCHA_MARKERS):
            return False
    submit_like = any(_is_submit_like(it) for it in items)
    if submit_like and not has_iframe:
        return False
    return True


def build_captcha_request_human_action(
    *,
    title: str,
    alert_digest: str,
    items: list[dict[str, Any]],
    aria_snapshot: str,
    form_html: str = "",
    executor_error: str | None = None,
) -> dict[str, Any]:
    """Scripted ``request_human`` for CAPTCHA walls (skip planner turns)."""
    why = explain_why_not_automated(
        title=title,
        alert_digest=alert_digest,
        items=items,
        aria_snapshot=aria_snapshot,
        form_html=form_html,
        executor_error=executor_error,
    )
    instructions = (
        "Complete the human verification in the **live browser** tab (e.g. press-and-hold in the "
        "challenge widget). Telegram only pauses the agent—the screenshot is not clickable. "
        f"{why}"
    )
    return {
        "op": "request_human",
        "reason": "Human verification (CAPTCHA)",
        "instructions": instructions,
        "describe": "fast-path: captcha / iframe verification wall",
        "wait_for_owner": True,
    }


def explain_why_not_automated(
    *,
    title: str,
    alert_digest: str,
    items: list[dict[str, Any]],
    aria_snapshot: str,
    form_html: str = "",
    executor_error: str | None = None,
) -> str:
    """Structural reasons the browser executor cannot complete this screen (no site-specific URLs)."""
    parts: list[str] = []
    aria_l = (aria_snapshot or "").lower()
    html_l = (form_html or "").lower()
    has_iframe = "iframe" in aria_l or "<iframe" in html_l
    submit_buttons = [
        it
        for it in items
        if str(it.get("tag", "")).lower() == "button"
        and str(it.get("type", "")).lower() == "submit"
    ]
    non_nav_buttons = [
        it
        for it in items
        if str(it.get("tag", "")).lower() == "button"
        and str(it.get("id", "")).lower() not in ("back-button",)
        and str(it.get("type", "")).lower() != "submit"
        and "ayuda" not in str(it.get("text", "")).lower()
        and "help" not in str(it.get("aria", "")).lower()
    ]

    if has_iframe:
        parts.append(
            "The challenge control lives in a cross-origin iframe and is not listed as an interactive ref."
        )
    if has_iframe and not submit_buttons and len(non_nav_buttons) == 0:
        parts.append(
            "The YAML interactive list only shows navigation/footer controls—not the verification widget."
        )
    if has_iframe and ("human" in html_l or "captcha" in html_l):
        parts.append(
            "Page markup indicates a human-verification region; timed press-and-hold is not a supported executor op."
        )
    if executor_error:
        head = executor_error.strip().split("\n", 1)[0]
        if head:
            parts.append(f"Last automation error on this screen: {head}")

    if parts:
        return " ".join(parts)
    return (
        "This step needs human action: the planner issued request_human because click/fill/combobox_pick "
        "cannot satisfy the visible challenge."
    )
