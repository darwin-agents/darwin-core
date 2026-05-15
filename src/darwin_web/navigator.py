from __future__ import annotations

import copy
import os
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from playwright.sync_api import Page

from darwin_web.executor import run_planner_action
from darwin_web.genhash import reset_pw_cache
from darwin_web.llm_client import LLMTurnTranscript, OpenRouterClient
from darwin_web.playbook import Playbook, PlaybookStep
from darwin_web.snapshot import (
    PageClosed,
    page_alert_digest,
    page_snapshot,
    safe_page_url,
    snapshot_prompt_block,
)
from darwin_web.step_screenshots import write_vision_input_png
from darwin_web.telegram_hil import consume_last_owner_telegram_reply

SYSTEM_PROMPT = """You are a browser automation planner. Minimize steps.

A screenshot of the current page may be attached as a second user message part (image). Use it together with the YAML element list. The first turn may have no image (blank or loading); use the YAML and URL only until a screenshot appears.

The element list in the user message is YAML (not JSON) for efficiency.

Reply with a single JSON object (no markdown fences). Schema:
{
  "thought": "one short sentence",
  "action": { ... }
}

The "action" value MUST be one JSON object, never an array. Wrong: "action": [{...}]. Right: "action": {...}.
The action object must have "op" at the TOP level. Wrong: "action": {"fill": {"op":"fill",...}}. Right: "action": {"op":"fill",...}.
Execute only ONE browser step per reply; do not return a list of future steps.

Every action EXCEPT "done" and "request_human" MUST include string field "describe": one clear sentence for a human recipe,
e.g. "Enter Mary in the first name text field" or "Click the blue Sign up button".

The "action" object must include string field "op". Allowed values:
- goto: {"op":"goto","url":"https://...","describe":"..."}
- click: {"op":"click","ref": <int>, "describe":"..."}
- fill: {"op":"fill","ref": <int>, "value": "<text>", "clear_first": true|false, "describe":"..."}  (for text inputs; on native <select> the runner uses select_option automatically). For **new** username / email local parts use ``"$GENHASH"`` (optional digits: ``$GENHASH2`` counts the same) or put that token as the **local part** before ``@`` (e.g. ``$GENHASH2@gmail.com``) — the executor replaces it with a random lowercase+digits token (not on **First/Last name** fields: use realistic names there). For **password** and **confirm** fields use ``"$GENHASH_PW"`` (same literal for both on one screen; the executor expands once so they match). Never put those sentinels on inputs whose name is ``firstName`` / ``lastName`` or whose label is "First name" / "Last name". If the snapshot already shows that ref's value equals your expanded string, the executor skips the fill — pick a different action. Never use fill on ``type=radio`` or ``type=checkbox`` — use **click** on that ref instead.
- select_option: {"op":"select_option","ref": <int>, "value": "<option value or visible label>", "describe":"..."}  (native <select> only)
- pick_option: {"op":"pick_option","label":"<visible row text>", "describe":"..."}  (custom listbox after it is open: uses role=option, e.g. month "January". Same field may be named "value" or "text" instead of "label". Do not use for native <select> — use select_option there.)
- press: {"op":"press","key": "<Playwright key e.g. Enter>", "ref": <optional int>, "describe":"..."}
- wait_ms: {"op":"wait_ms","ms": <int 0-60000>, "describe":"..."}
- scroll_into_view: {"op":"scroll_into_view","ref": <int>, "describe":"..."}
- request_human: {"op":"request_human","reason":"<short title>","instructions":"<what the owner should know or do>","describe":"optional one-line for logs","wait_for_owner": true|false, "max_wait_s": <optional seconds>} — when the page needs a real human (CAPTCHA, device approval, OTP you cannot read, ambiguous UI). Does not automate the page. If Telegram HIL is configured, the runtime sends **reason**, **instructions**, and optional screenshot to the owner—**instructions must match what you see** (headlines, errors, language question), not generic QR text unless the screenshot shows a QR wall. After the owner replies, their message appears on the **next** turn under **Owner message (Telegram)**; use it to choose the next action. Owners can write in plain language or send ``/continue`` when the tab is already in the right state.
- done: {"op":"done","summary": "<what was completed>"} — **only** when USER_GOAL is **fully** achieved (e.g. account created and signed in, purchase confirmed, target page reached as stated). Wrong: declaring done after an intermediate screen, because "the next step is obvious", or summarizing progress as "up to" / "partially" / "so far". If the goal is a multi-step flow, keep issuing concrete actions until the goal is satisfied or you use request_human for a hard wall.

Use only refs that appear in the latest element list (pick_option is the exception: it targets visible role=option by label text). Prefer click/fill over exploratory gotos.
If an element might be off-screen, use scroll_into_view before click/fill.

Read each input's "value" in the list: if it already equals the text you would type, do NOT use fill on that ref again.
For role=combobox widgets, also read "text": if it already shows the chosen label (e.g. "Month January"), treat that field as set; do not click it again just because "value" is empty.

When the **screenshot** or the **Visible page alerts/errors (DOM)** line shows validation errors (red text, red field outline, "taken", "invalid", "try another", wrong code, etc.), fix the situation before declaring done: change the input to a clearly different value, or **click** an offered alternative the site shows (suggested address, "Available: …" link, radio row, secondary button). Prefer those built-in suggestions over inventing another similar string.

**Email / SMS / authenticator codes:** You cannot read the user's inbox or SMS from this browser. Never invent codes, never use placeholders like ``new_verification_code``, ``123456``, ``654321``, or random alphanumeric strings as if they were real OTPs. If the page asks for a code sent to an email or phone, use ``request_human`` so a person can supply it (quote any **Visible page alerts/errors** text in **instructions**), or click **Back / Atrás** and choose another path if the run must stay unattended.

For a **new** username when no preset applies, prefer ``"$GENHASH"`` over inventing your own string. For passwords prefer ``"$GENHASH_PW"`` (see fill action rules). **Never** use those sentinels on given-name / family-name fields.

If the **URL and form stay the same** after clicking Next / Continue, the submission did not succeed: read the **screenshot** for errors, change inputs or pick offered alternatives—do **not** only repeat the same button click.

Many signup flows show an email domain (e.g. ``@example.com``) **beside** the text box: type only the **local part** in that box unless the label clearly asks for a full address.

When required fields already contain reasonable text, advance the flow with click on the primary Next/Continue/Submit button
(or another empty field). Re-filling the same ref with the same text is almost always wrong.

If the USER_GOAL is a multi-step flow (e.g. sign-up), you must move past each screen—one fill is rarely enough for the whole goal.

For elements with "tag": "select", use select_option (or fill with the same value—either works on native dropdowns). Use the option's value attribute or visible label text (e.g. month "January" or "1" depending on the control).

For role=combobox (or similar) custom dropdowns: click once to open the list if needed, then use pick_option with the exact visible option text (e.g. {"op":"pick_option","label":"January"} or {"op":"pick_option","label":"Enero"} for Spanish). Google often shows the chosen month in ``text`` as ``Month January`` (English) or ``Mes Enero`` (Spanish) while ``value`` stays empty—that still means the month is selected; do not re-open the month menu unless changing the month. After options are visible, do not click the combobox trigger again unless the menu closed.

On screens with two password fields (Password + Confirm): fill BOTH with the **same** string — use ``"$GENHASH_PW"`` for each fill on that screen (the executor reuses one random password), then click Next. Never leave Confirm empty.

Return JSON with "thought" and "action".
"""


def _nav_breadcrumb(url: str) -> str:
    """Host + path without query — stable across Google TL= tokens so we can reset stale errors on real navigation."""
    try:
        p = urlparse(url)
        return f"{p.netloc}{p.path}".lower()
    except Exception:  # noqa: BLE001
        return (url or "")[:160].lower()


def _done_summary_describes_partial_progress(summary: str) -> bool:
    """Catch common misuse: ``done`` with milestone / partial wording instead of full USER_GOAL completion."""
    s = (summary or "").lower()
    return any(
        phrase in s
        for phrase in (
            " up to ",
            " up to the",
            " partial ",
            "partially",
            " so far ",
            " not yet complete",
            " not complete",
            "next step",
            " before finishing",
            " halfway",
            "not finished",
        )
    )


def _listbox_open_hint(items: list[dict[str, Any]]) -> str:
    """When snapshot lists role=option rows, steer away from re-clicking the combobox."""
    if not any(
        isinstance(i.get("role"), str) and i.get("role").strip().lower() == "option" for i in items
    ):
        return ""
    return (
        '\nNOTE: A listbox menu is visible (elements with "role":"option" in the list). '
        'Choose one with {"op":"pick_option","label":"<exact visible text>"} '
        '(e.g. {"op":"pick_option","label":"January"} or {"op":"pick_option","label":"Enero"}) or click that option ref. '
        "Avoid clicking the Month/Gender combobox trigger again while options are shown.\n"
    )


def _radio_group_with_text_username_hint(items: list[dict[str, Any]]) -> str:
    """Signup UIs often pair several ``type=radio`` presets with one text field—suffix edits loop forever."""
    radios = [
        it
        for it in items
        if str(it.get("tag", "")).lower() == "input" and str(it.get("type", "")).lower() == "radio"
    ]
    if len(radios) < 2:
        return ""
    for it in items:
        if str(it.get("tag", "")).lower() != "input":
            continue
        t = str(it.get("type", "")).lower()
        if t not in ("", "text", "email"):
            continue
        nm = str(it.get("name", "")).strip().lower()
        ar = str(it.get("aria", "")).strip().lower()
        if nm == "username" or "username" in ar or "gmail" in ar or "email address" in ar:
            return (
                "\nNOTE: This screen shows **radio** choices plus a **custom** text field. If the screenshot shows "
                '"taken" / invalid for custom, do **not** tweak the same base with small suffix changes. Prefer: '
                "(1) **click** a preset radio ref to pick an offered address, OR (2) `fill` custom with a **long random** "
                "alphanumeric local part (many random letters/digits, e.g. 16–24 chars).\n"
            )
    return ""


def _birthday_month_committed_hint(items: list[dict[str, Any]]) -> str:
    """Custom month comboboxes (e.g. Google) often keep ``value`` empty; the label lives in ``text``."""
    for it in items:
        if str(it.get("role", "")).strip().lower() != "combobox":
            continue
        t = str(it.get("text", "")).strip()
        tl = t.lower()
        rest = ""
        if tl.startswith("month "):
            rest = t[6:].strip()
        elif tl.startswith("mes "):
            rest = t[4:].strip()
        if not rest:
            continue
        return (
            '\nNOTE: If a combobox `text` looks like "Month January" or "Mes Enero", the month is usually ALREADY selected '
            "(the page puts the label in `text`, not `value`). Do NOT `click` that month combobox again unless "
            "you intend to change the month. Continue with the **gender** combobox (often `text` is exactly `Gender` or "
            "`Género` when unset), then `pick_option` with the visible row text, then Next / Siguiente.\n"
        )
    return ""


def _human_wall_page_hint(title: str, url: str) -> str:
    """Nudge the planner toward ``request_human`` on common account-verification walls."""
    tl = (title or "").lower()
    ul = (url or "").lower()
    if "verificar" in tl and ("correo" in tl or "dirección" in tl or "direccion" in tl):
        return (
            "\nNOTE: This looks like an **email / address verification** step (Spanish). You cannot read the inbox from here. "
            'Do **not** guess verification codes. Prefer {"op":"request_human",...} with **instructions** that name the '
            "destination address from the page and ask the owner to paste the code from email (or spam). Quote any "
            "**Visible page alerts/errors** line if the last attempt failed.\n"
        )
    if "verify your email" in tl or ("verify" in tl and "email" in tl and "password" not in tl):
        return (
            "\nNOTE: **Email verification** title detected. Do **not** fabricate OTPs. Use **request_human** so the owner "
            "can enter the real code, or go Back if automation cannot continue unattended.\n"
        )
    if "try again" in tl or "different phone" in tl or "please try again" in tl:
        return (
            "\nNOTE: This title suggests a **verification error or retry** (read the screenshot body text). If you use "
            '`request_human`, **instructions** must summarize the visible problem for the owner (exact error meaning, '
            'e.g. phone limit / need another number / click Next then scan again) - not a generic "scan the QR" when the '
            "page already states a specific issue.\n"
        )
    if "verify" in tl and ("account" in tl or "creating" in tl or "before" in tl):
        return (
            "\nNOTE: This page title suggests a human-only verification wall (e.g. QR on your phone). "
            'Prefer {"op":"request_human",...} over guessing clicks. In **instructions**, say what the screenshot shows '
            "(e.g. waiting for verification, scan QR) and any visible warnings.\n"
        )
    if "accounts.google.com" in ul and "signin" in ul and "challenge" in ul:
        return (
            "\nNOTE: Google sign-in challenge flow often requires the account owner on another device. "
            'Consider {"op":"request_human",...} if automation cannot proceed.\n'
        )
    return ""


def _verification_code_field_hint(items: list[dict[str, Any]], title: str) -> str:
    """Detect OTP / verification inputs from labels (works without relying on vision)."""
    tl = (title or "").lower()
    title_signals = (
        "código" in tl
        or "codigo" in tl
        or "verification code" in tl
        or ("verify" in tl and "code" in tl)
    )
    code_markers = (
        "verification code",
        "código",
        "codigo",
        "enter code",
        "introduce el código",
        "introduce el codigo",
        "sms code",
        "one-time",
        "otp",
    )
    field_hit = False
    for it in items:
        if str(it.get("tag", "")).lower() != "input":
            continue
        if str(it.get("type", "")).lower() in ("hidden", "password", "checkbox", "radio", "submit", "button"):
            continue
        blob = " ".join(
            str(it.get(k) or "").lower() for k in ("aria", "placeholder", "name", "id", "text")
        )
        if any(m in blob for m in code_markers):
            field_hit = True
            break
    if not field_hit and not title_signals:
        return ""
    return (
        "\n!!! AUTONOMY: This screen expects a **verification code** from email/SMS/authenticator. "
        "You do **not** have access to that secret. **Do not** fill random strings, variable names, or sequential digits. "
        'Use {"op":"request_human",...} (owner reads inbox / SMS and enters the code), or **click** Back / Atrás and pick '
        "another signup path if no human is available.\n"
    )


def _consecutive_same_ref_fill_streak(
    recent: deque[tuple[str, int | None, str | None]],
) -> tuple[int, int] | None:
    """If executed steps ending now are all ``fill`` on one ref, return (ref, count); else None."""
    ref: int | None = None
    count = 0
    for o, r, _ in reversed(recent):
        if o != "fill" or not isinstance(r, int):
            break
        if ref is None:
            ref, count = r, 1
        elif r == ref:
            count += 1
        else:
            break
    if ref is None or count < 2:
        return None
    return ref, count


def _consecutive_same_ref_fill_hint(recent: deque[tuple[str, int | None, str | None]]) -> str:
    """After repeated fills on one control, force a strategy change (validation loop / guessed OTP)."""
    st = _consecutive_same_ref_fill_streak(recent)
    if st is None:
        return ""
    ref, n = st
    tail = (
        f"\n!!! AUTONOMY: The last **{n}** executed steps were **fill** on the **same ref {ref}**. "
        "The site is likely **rejecting** the value (wrong code, invalid format, placeholder). "
        "Do **not** fill that ref again with another guess. Read **Visible page alerts/errors** and the screenshot; "
        "then either fix the underlying issue, **click** a different control, or use **request_human** if a real secret "
        "(OTP) is required.\n"
    )
    if n >= 3:
        tail += (
            "Because this repeated **3+** times: **stop** guessing—use **request_human** if this field is for an "
            "email/SMS code, or clear the field and use a substantively different strategy.\n"
        )
    return tail


def _google_birthday_screen_hint(items: list[dict[str, Any]], url: str) -> str:
    """Google signup birthday/gender: steer away from re-clicking month when Gender/Género is still unset."""
    if "birthdaygender" not in url.lower():
        return ""
    for it in items:
        if str(it.get("role", "")).strip().lower() != "combobox":
            continue
        tx = str(it.get("text", "")).strip()
        if tx in ("Gender", "Género"):
            return (
                "\nNOTE: Google birthday/gender: if Day and Year already have values in the YAML list, do NOT fill them "
                "again. If a month combobox already shows a chosen month in `text` (English ``Month January`` or Spanish "
                "``Mes Enero``), do **not** keep clicking that month control—**open the gender combobox** (unset when `text` "
                'is exactly ``Gender`` or ``Género``), then '
                '`{"op":"pick_option","label":"Female"}` / `Mujer` / `Male` / `Hombre` / `Rather not say` / '
                '`Prefiero no decirlo` / `Custom` / `Personalizado` — whichever row text is visible—then click Next or '
                "Siguiente.\n"
            )
    return ""


def _password_screen_hint(
    items: list[dict[str, Any]], title: str, url: str, last_action: dict[str, Any] | None
) -> str:
    """Password + confirm: YAML often hides masked values; use aria labels and last fill when needed."""
    tl = (title or "").lower()
    ul = url.lower()
    if "password" not in tl and "signup/password" not in ul and "/password" not in ul:
        return ""
    pwd_rows = [
        it
        for it in items
        if str(it.get("tag", "")).lower() == "input" and str(it.get("type", "")).lower() == "password"
    ]
    if len(pwd_rows) < 2:
        return ""
    by_aria: dict[str, int] = {}
    for it in pwd_rows:
        ar = str(it.get("aria") or "").strip().lower()
        r = it.get("ref")
        if ar in ("password", "confirm") and isinstance(r, int):
            by_aria[ar] = r
    empty_refs: list[int] = []
    filled_refs: list[int] = []
    for it in pwd_rows:
        ref = it.get("ref")
        if not isinstance(ref, int):
            continue
        raw = it.get("value")
        cur = str(raw).strip() if isinstance(raw, str) else ""
        if cur:
            filled_refs.append(ref)
        else:
            empty_refs.append(ref)
    if len(empty_refs) == 1 and len(filled_refs) == 1:
        er, fr = empty_refs[0], filled_refs[0]
        return (
            f"\nNOTE: Password screen: ref {fr} shows a value but ref {er} (Confirm) is empty. "
            f"Fill ref {er} with the **exact same** password, then click Next.\n"
        )
    if len(empty_refs) >= 2 and last_action and last_action.get("op") == "fill":
        lr = last_action.get("ref")
        if isinstance(lr, int) and "password" in by_aria and "confirm" in by_aria:
            if lr == by_aria["password"]:
                cr = by_aria["confirm"]
                return (
                    f"\nNOTE: Masked password fields may both show empty `value` in the list. You filled ref {lr} (Password). "
                    f"Next fill ref {cr} (Confirm) with the **same** string, then click Next.\n"
                )
            if lr == by_aria["confirm"]:
                return "\nNOTE: Confirm was filled; click Next unless the page shows a validation error.\n"
    if len(empty_refs) >= 2:
        return (
            "\nNOTE: Both password fields look empty in the list: fill Password, then Confirm with the **same** string, "
            "then Next.\n"
        )
    return ""


def _stuck_fill_hint(items: list[dict[str, Any]], last_action: dict[str, Any] | None) -> str:
    """Nudge the planner when it is about to repeat a redundant fill (same ref, value already in DOM)."""
    if not last_action or last_action.get("op") != "fill":
        return ""
    ref = last_action.get("ref")
    want = last_action.get("value")
    if not isinstance(ref, int) or not isinstance(want, str):
        return ""
    want_s = want.strip()
    if not want_s:
        return ""
    for it in items:
        if it.get("ref") != ref:
            continue
        cur = it.get("value")
        if isinstance(cur, str) and cur.strip() == want_s:
            return (
                "\n!!! STUCK-PREVENTION: Your last turn used fill on this ref with this exact text, "
                "and the snapshot still shows the same value in that field. Do NOT fill that ref again. "
                "If that value is wrong for the goal (placeholder, taken, invalid), **replace** it with a clearly different "
                "string (see system rules for unique usernames) or pick a site suggestion from the screenshot. "
                "Otherwise use click on Next/Continue once, or fill a different empty field.\n"
            )
    return ""


def _stuck_repeated_click_hint(recent: deque[tuple[str, int | None, str | None]]) -> str:
    """Several identical ``click`` steps in a row usually mean validation blocked navigation."""
    if len(recent) < 3:
        return ""
    tail = list(recent)[-3:]
    if not all(o == "click" for o, _, _ in tail):
        return ""
    r0, r1, r2 = (tail[0][1], tail[1][1], tail[2][1])
    if not (isinstance(r0, int) and r0 == r1 == r2):
        return ""
    return (
        f"\n!!! STUCK-PREVENTION: The last **3 executed** steps were all **click** on ref {r0}. "
        "If the screenshot and URL look **unchanged**, that control is not advancing the flow—do **not** keep clicking it. "
        "Read visible error text; **fill** a new value if a field failed validation; use **pick_option** / radio refs if "
        "the site offers alternatives; ``wait_ms`` once if the UI is still updating; or ``request_human`` if blocked.\n"
    )


_LIKELY_PLACEHOLDER_USERNAMES = frozenset(
    {
        "youruniqueusername",
        "username",
        "user",
        "test",
        "admin",
        "email",
        "newuser",
        "myusername",
        "uniqueusername",
        "youremail",
    }
)


def _is_likely_placeholder_username(val: str) -> bool:
    v = val.strip().lower()
    if not v:
        return False
    if v in _LIKELY_PLACEHOLDER_USERNAMES:
        return True
    if "yourunique" in v:
        return True
    if v.startswith("testuser") and len(v) < 16:
        return True
    return False


def _signup_username_step_hint(url: str, items: list[dict[str, Any]]) -> str:
    """``/signup/username`` (e.g. Google): YAML often has only one text field—radios appear only after errors."""
    if "/signup/username" not in (url or "").lower():
        return ""
    base = (
        "\nNOTE: **Username / Gmail local part** step: helper text often allows only letters, numbers, and periods. "
        "Prefer ``fill`` with value ``\"$GENHASH\"`` (executor generates a random local part). If **Next** was already used "
        "and the **URL is unchanged**, check the screenshot for inline errors and **change** the username (or choose "
        "suggested radios if they appear)—not another blind Next.\n"
    )
    for it in items:
        if str(it.get("tag", "")).lower() != "input":
            continue
        if str(it.get("type", "")).lower() not in ("", "text", "email"):
            continue
        if str(it.get("name", "")).strip().lower() != "username":
            continue
        raw = it.get("value")
        if not isinstance(raw, str):
            return base
        if _is_likely_placeholder_username(raw):
            return (
                base
                + f"The field's current YAML `value` ({raw.strip()!r}) looks like a **placeholder**—clear it and "
                "``fill`` with ``\"$GENHASH\"`` (or pick a site suggestion) before trying Next again.\n"
            )
        return base
    return base


def _coerce_planner_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """Fix common model shapes: ``action`` as a list, nested op dicts, or steps under other keys."""
    action = raw.get("action")
    if isinstance(action, dict) and action.get("op") is None:
        for _k, v in action.items():
            if isinstance(v, dict) and isinstance(v.get("op"), str):
                raw["action"] = v
                action = v
                break
    if isinstance(action, list):
        chosen: dict[str, Any] | None = None
        for item in action:
            if isinstance(item, dict) and item.get("op") is not None:
                chosen = item
                break
        if chosen is None and action and isinstance(action[0], dict):
            chosen = action[0]
        raw["action"] = chosen
    elif action is None or not isinstance(action, dict):
        for key in ("actions", "next_actions", "steps", "plan"):
            alt = raw.get(key)
            if isinstance(alt, list) and alt:
                first = alt[0]
                if isinstance(first, dict) and first.get("op") is not None:
                    raw["action"] = first
                    break
                if isinstance(first, dict) and isinstance(first.get("action"), dict):
                    raw["action"] = first["action"]
                    break
    return raw


def _llm_turn_artifact_path(artifacts_dir: Path, turn: int) -> Path:
    return artifacts_dir / f"{turn:03d}-llm-turn.yaml"


def _vision_rel_for_yaml(artifacts_dir: Path, vision_path: Path | None) -> str | None:
    if vision_path is None:
        return None
    try:
        return str(vision_path.resolve().relative_to(artifacts_dir.resolve()))
    except ValueError:
        return vision_path.name


def _write_llm_turn_yaml(
    path: Path,
    *,
    turn: int,
    page_url: str,
    request_model: str,
    prompt_debug: dict[str, Any],
    planner: dict[str, Any] | None,
    transcript: LLMTurnTranscript | None,
    parsed_after_coerce: dict[str, Any] | None,
    execution: dict[str, Any] | None,
    error: str | None,
) -> None:
    """Single artifact: prompt (what the planner saw), response, merged planner + execution."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any] = {
        "kind": "darwin_web_llm_turn",
        "turn": turn,
        "page_url": page_url,
        "request": {"model": request_model},
        "prompt": prompt_debug,
    }
    if planner is not None:
        doc["planner"] = planner
    if transcript is not None:
        doc["response"] = {
            "assistant_text": transcript.assistant_raw,
            "assistant_parsed": transcript.assistant_parsed,
        }
        doc["openrouter"] = {
            "id": transcript.openrouter_id,
            "model": transcript.openrouter_model,
            "usage": transcript.usage,
            "finish_reason": transcript.finish_reason,
        }
    if parsed_after_coerce is not None:
        doc["assistant_after_coerce"] = parsed_after_coerce
    if execution is not None:
        doc["execution"] = execution
    if error is not None:
        doc["error"] = error
    path.write_text(
        yaml.safe_dump(
            doc,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=120,
        ),
        encoding="utf-8",
    )


def _vision_default(vision: bool | None) -> bool:
    if vision is not None:
        return vision
    v = os.getenv("DARWIN_WEB_VISION", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _screenshot_relpath(playbook_out: Path | None, shot_path: Path) -> str:
    if playbook_out is None:
        return shot_path.name
    try:
        return str(shot_path.resolve().relative_to(playbook_out.parent.resolve()))
    except ValueError:
        return shot_path.name


@dataclass
class NavigationResult:
    playbook: Playbook
    completed: bool
    errors: list[str]
    planner_turns: int


def run_goal(
    *,
    page: Page,
    goal: str,
    llm: OpenRouterClient,
    max_steps: int,
    artifacts_dir: Path | None = None,
    playbook_out: Path | None = None,
    vision: bool | None = None,
) -> NavigationResult:
    """LLM-guided navigation; on success (op done) builds a YAML :class:`Playbook`.

    When *artifacts_dir* is set and vision is enabled (default), saves ``NNN-vision-input.png``
    (state before each planner call, except turn 1 which is skipped as often blank) and sends it to the planner.
    Playbook ``screenshot_after`` points at ``(N+1)-vision-input.png`` (post-step UI, captured at the start of the next
    planner turn, or at end of run if the last turn hits ``max_steps``). Vision is skipped if *artifacts_dir* is omitted.
    """
    errors: list[str] = []
    recorded: list[PlaybookStep] = []
    completed = False
    final_summary: str | None = None
    last_turn = 0
    last_executed_action: dict[str, Any] | None = None
    action_tail: deque[tuple[str, int | None, str | None]] = deque(maxlen=8)

    if artifacts_dir is not None:
        artifacts_dir.mkdir(parents=True, exist_ok=True)

    reset_pw_cache()
    use_vision = _vision_default(vision)

    last_nav_key: str | None = None

    for turn in range(1, max_steps + 1):
        last_turn = turn
        try:
            items, snap_url = page_snapshot(page)
        except PageClosed as exc:
            errors.append(str(exc))
            break
        nav_key = _nav_breadcrumb(snap_url)
        if last_nav_key is not None and nav_key != last_nav_key:
            errors.clear()
            action_tail.clear()
            reset_pw_cache()
        last_nav_key = nav_key
        try:
            title = page.title()
        except Exception:
            title = ""

        try:
            alert_digest = page_alert_digest(page)
        except Exception:  # noqa: BLE001
            alert_digest = ""
        digest_block = ""
        if alert_digest:
            digest_block = f"\nVisible page alerts/errors (DOM):\n{alert_digest}\n"

        err_tail = ""
        if errors:
            err_tail = "\nRecent errors (fix or work around):\n" + "\n".join(f"- {e}" for e in errors[-6:])

        stuck_hint = _stuck_fill_hint(items, last_executed_action)
        repeat_click_hint = _stuck_repeated_click_hint(action_tail)
        same_ref_fill_hint = _consecutive_same_ref_fill_hint(action_tail)
        listbox_hint = _listbox_open_hint(items)
        month_done_hint = _birthday_month_committed_hint(items)
        wall_hint = _human_wall_page_hint(title, snap_url)
        otp_hint = _verification_code_field_hint(items, title)
        google_bday_hint = _google_birthday_screen_hint(items, snap_url)
        pwd_pair_hint = _password_screen_hint(items, title, snap_url, last_executed_action)
        radio_username_hint = _radio_group_with_text_username_hint(items)
        signup_username_hint = _signup_username_step_hint(snap_url, items)

        owner_reply = consume_last_owner_telegram_reply()
        owner_block = ""
        if owner_reply:
            owner_block = (
                "\nOwner message (Telegram; treat as authoritative guidance for this turn):\n"
                f"{owner_reply}\n"
            )

        user_block = (
            f"USER_GOAL:\n{goal}\n"
            + owner_block
            + "\n"
            + snapshot_prompt_block(items, snap_url, title)
            + digest_block
            + stuck_hint
            + repeat_click_hint
            + same_ref_fill_hint
            + listbox_hint
            + month_done_hint
            + google_bday_hint
            + pwd_pair_hint
            + radio_username_hint
            + signup_username_hint
            + wall_hint
            + otp_hint
            + err_tail
            + '\n\nReturn JSON with "thought" and "action".'
        )

        vision_path: Path | None = None
        if artifacts_dir is not None and use_vision and turn >= 2:
            vision_path = write_vision_input_png(page, artifacts_dir, turn)

        prompt_debug: dict[str, Any] = {
            "user_text": user_block,
            "elements_format": "yaml",
            "vision_image": _vision_rel_for_yaml(artifacts_dir, vision_path) if artifacts_dir else None,
        }

        transcript: LLMTurnTranscript | None = None
        raw: dict[str, Any] | None = None
        try:
            transcript = llm.chat_planner_turn(
                user_block,
                system_prompt=SYSTEM_PROMPT,
                vision_png_path=vision_path,
            )
            raw = copy.deepcopy(transcript.assistant_parsed)
            _coerce_planner_raw(raw)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"llm:{exc}")
            if artifacts_dir is not None:
                _write_llm_turn_yaml(
                    _llm_turn_artifact_path(artifacts_dir, turn),
                    turn=turn,
                    page_url=safe_page_url(page),
                    request_model=llm.model,
                    prompt_debug=prompt_debug,
                    planner=None,
                    transcript=None,
                    parsed_after_coerce=None,
                    execution=None,
                    error=str(exc),
                )
            continue

        action = raw.get("action")
        if not isinstance(action, dict):
            errors.append(f"turn {turn}: missing action dict, got {type(action).__name__}")
            if artifacts_dir is not None:
                _write_llm_turn_yaml(
                    _llm_turn_artifact_path(artifacts_dir, turn),
                    turn=turn,
                    page_url=safe_page_url(page),
                    request_model=llm.model,
                    prompt_debug=prompt_debug,
                    planner={"thought": raw.get("thought"), "action": None},
                    transcript=transcript,
                    parsed_after_coerce=copy.deepcopy(raw),
                    execution=None,
                    error=f"missing action dict, got {type(action).__name__}",
                )
            continue

        if action.get("op") == "done":
            summary = action.get("summary")
            if isinstance(summary, str) and _done_summary_describes_partial_progress(summary):
                msg = (
                    f"turn {turn}: ignored invalid done — USER_GOAL must be fully achieved, "
                    f"not a milestone summary ({summary.strip()[:160]!r})."
                )
                errors.append(msg)
                last_executed_action = None
                if artifacts_dir is not None:
                    exec_doc: dict[str, Any] = {
                        "continue_loop": True,
                        "executor_message": msg,
                        "execute_exception": None,
                        "screenshot_after": None,
                        "invalid_done_refused": True,
                    }
                    _write_llm_turn_yaml(
                        _llm_turn_artifact_path(artifacts_dir, turn),
                        turn=turn,
                        page_url=safe_page_url(page),
                        request_model=llm.model,
                        prompt_debug=prompt_debug,
                        planner={"thought": raw.get("thought"), "action": copy.deepcopy(action)},
                        transcript=transcript,
                        parsed_after_coerce=copy.deepcopy(raw),
                        execution=exec_doc,
                        error=None,
                    )
                continue

        pb_step: PlaybookStep | None = None
        cont = True
        err: str | None = None
        execute_exception: str | None = None
        try:
            cont, pb_step, err, _meta = run_planner_action(page, action, vision_png_path=vision_path)
        except Exception as exc:  # noqa: BLE001
            execute_exception = str(exc)
            errors.append(f"turn {turn}: execute:{exc}")

        if err:
            errors.append(f"turn {turn}: {err}")

        next_vision_rel: str | None = None
        if artifacts_dir is not None and use_vision:
            next_vision_rel = _screenshot_relpath(
                playbook_out, artifacts_dir / f"{turn + 1:03d}-vision-input.png"
            )

        if pb_step is not None:
            if next_vision_rel is not None:
                pb_step.screenshot_after = next_vision_rel
            recorded.append(pb_step)
            if artifacts_dir is not None and use_vision and turn == max_steps:
                write_vision_input_png(page, artifacts_dir, turn + 1)
            opx = str(action.get("op") or "")
            rfx = action.get("ref")
            rip = rfx if isinstance(rfx, int) else None
            fill_snip: str | None = None
            if opx == "fill":
                fv = action.get("value")
                if isinstance(fv, str) and fv.strip():
                    fill_snip = fv.strip()[:48]
            action_tail.append((opx, rip, fill_snip))

        if artifacts_dir is not None:
            exec_doc: dict[str, Any] = {
                "continue_loop": cont,
                "executor_message": err,
                "execute_exception": execute_exception,
                "screenshot_after": next_vision_rel,
            }
            if pb_step is not None:
                exec_doc["recorded_step"] = pb_step.to_recipe_dict()
            _write_llm_turn_yaml(
                _llm_turn_artifact_path(artifacts_dir, turn),
                turn=turn,
                page_url=safe_page_url(page),
                request_model=llm.model,
                prompt_debug=prompt_debug,
                planner={"thought": raw.get("thought"), "action": copy.deepcopy(action)},
                transcript=transcript,
                parsed_after_coerce=copy.deepcopy(raw),
                execution=exec_doc,
                error=None,
            )

        last_executed_action = copy.deepcopy(action)

        if not cont:
            summary = action.get("summary")
            if isinstance(summary, str) and summary.strip():
                final_summary = summary.strip()
            else:
                final_summary = "done"
            completed = True
            break

    playbook = Playbook(goal=goal, steps=recorded, final_summary=final_summary)
    return NavigationResult(
        playbook=playbook,
        completed=completed,
        errors=errors,
        planner_turns=last_turn,
    )
