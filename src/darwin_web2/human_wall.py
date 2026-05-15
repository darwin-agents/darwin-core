"""Language-neutral explanations when automation cannot complete a verification wall."""

from __future__ import annotations

from typing import Any


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
