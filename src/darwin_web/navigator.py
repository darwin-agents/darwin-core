from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from playwright.sync_api import Page

from darwin_web.executor import run_planner_action
from darwin_web.llm_client import LLMTurnTranscript, OpenRouterClient
from darwin_web.playbook import Playbook, PlaybookStep
from darwin_web.snapshot import (
    PageClosed,
    page_snapshot,
    safe_page_url,
    snapshot_prompt_block,
)
from darwin_web.step_screenshots import write_step_png, write_vision_input_png

SYSTEM_PROMPT = """You are a browser automation planner. Minimize steps.

A screenshot of the current page may be attached as a second user message part (image). Use it together with the YAML element list.

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
- fill: {"op":"fill","ref": <int>, "value": "<text>", "clear_first": true|false, "describe":"..."}  (for text inputs; on native <select> the runner uses select_option automatically). If the snapshot already shows that ref's value equals your string, the executor skips the fill — pick a different action. Never use fill on ``type=radio`` or ``type=checkbox`` — use **click** on that ref instead.
- select_option: {"op":"select_option","ref": <int>, "value": "<option value or visible label>", "describe":"..."}  (native <select> only)
- pick_option: {"op":"pick_option","label":"<visible row text>", "describe":"..."}  (custom listbox after it is open: uses role=option, e.g. month "January". Same field may be named "value" or "text" instead of "label". Do not use for native <select> — use select_option there.)
- press: {"op":"press","key": "<Playwright key e.g. Enter>", "ref": <optional int>, "describe":"..."}
- wait_ms: {"op":"wait_ms","ms": <int 0-60000>, "describe":"..."}
- scroll_into_view: {"op":"scroll_into_view","ref": <int>, "describe":"..."}
- request_human: {"op":"request_human","reason":"<short title>","instructions":"<what the owner must do on their phone or in the browser>","describe":"optional one-line for logs","wait_for_owner": true|false, "max_wait_s": <optional seconds>} — when the page needs a real human (QR scan on another device, Google "verify some info", SMS code on the owner's phone, CAPTCHA). Does not automate the page. If Telegram HIL is configured in the runtime environment, sends the current turn's screenshot (when vision is on) plus text to the owner; default wait_for_owner true blocks until they reply /continue or done. Use this instead of useless click/fill loops on bot walls.
- done: {"op":"done","summary": "<what was completed>"} — only when the user's goal is fully satisfied

Use only refs that appear in the latest element list (pick_option is the exception: it targets visible role=option by label text). Prefer click/fill over exploratory gotos.
If an element might be off-screen, use scroll_into_view before click/fill.

Read each input's "value" in the list: if it already equals the text you would type, do NOT use fill on that ref again.
For role=combobox widgets, also read "text": if it already shows the chosen label (e.g. "Month January"), treat that field as set; do not click it again just because "value" is empty.

When required fields already contain reasonable text, advance the flow with click on the primary Next/Continue/Submit button
(or another empty field). Re-filling the same ref with the same text is almost always wrong.

If the USER_GOAL is a multi-step flow (e.g. sign-up), you must move past each screen—one fill is rarely enough for the whole goal.

For elements with "tag": "select", use select_option (or fill with the same value—either works on native dropdowns). Use the option's value attribute or visible label text (e.g. month "January" or "1" depending on the control).

For role=combobox (or similar) custom dropdowns: click once to open the list if needed, then use pick_option with the exact visible option text (e.g. {"op":"pick_option","label":"January"}). After options are visible, do not click the combobox trigger again unless the menu closed.

On screens with two password fields (Password + Confirm): fill BOTH with the **same** string (often two fill steps), then click Next. Never leave Confirm empty.

Return JSON with "thought" and "action".
"""


def _nav_breadcrumb(url: str) -> str:
    """Host + path without query — stable across Google TL= tokens so we can reset stale errors on real navigation."""
    try:
        p = urlparse(url)
        return f"{p.netloc}{p.path}".lower()
    except Exception:  # noqa: BLE001
        return (url or "")[:160].lower()


def _google_create_email_choice_hint(title: str, url: str, items: list[dict[str, Any]]) -> str:
    """Google 'Create an email address' uses radios + optional text; ``fill`` on radios is wrong."""
    tl = (title or "").lower()
    ul = url.lower()
    if "create an email address" not in tl:
        return ""
    if "signup/username" not in ul and "/lifecycle/steps/signup/" not in ul:
        return ""
    if not any(
        str(it.get("type", "")).lower() == "radio" and str(it.get("name", "")).strip() == "usernameRadio"
        for it in items
    ):
        return ""
    return (
        "\nNOTE: This Gmail step uses **radio** choices plus an optional text box. Use **click** on a radio ref to pick a "
        "suggested address or the custom option — do **not** use `fill` on `type: radio`. After choosing custom, `fill` the "
        "**text** input (name Username / aria \"Create a Gmail address\"), then click Next.\n"
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
        '(e.g. {"op":"pick_option","label":"January"}) or click that option ref. '
        "Avoid clicking the Month/Gender combobox trigger again while options are shown.\n"
    )


def _birthday_month_committed_hint(items: list[dict[str, Any]]) -> str:
    """Custom month comboboxes (e.g. Google) often keep ``value`` empty; the label lives in ``text`` (``Month January``)."""
    for it in items:
        if str(it.get("role", "")).strip().lower() != "combobox":
            continue
        t = str(it.get("text", "")).strip()
        if not t.lower().startswith("month "):
            continue
        rest = t[6:].strip()
        if not rest:
            continue
        return (
            '\nNOTE: If a combobox `text` looks like "Month January", the month is usually ALREADY selected '
            "(the page puts the label in `text`, not `value`). Do NOT `click` that month combobox again unless "
            "you intend to change the month. Continue with `fill` on Day and Year inputs, then Gender.\n"
        )
    return ""


def _human_wall_page_hint(title: str, url: str) -> str:
    """Nudge the planner toward ``request_human`` on common account-verification walls."""
    tl = (title or "").lower()
    ul = (url or "").lower()
    if "verify" in tl and ("account" in tl or "creating" in tl or "before" in tl):
        return (
            "\nNOTE: This page title suggests a human-only verification wall (e.g. QR on your phone). "
            'Prefer {"op":"request_human",...} over guessing clicks.\n'
        )
    if "accounts.google.com" in ul and "signin" in ul and "challenge" in ul:
        return (
            "\nNOTE: Google sign-in challenge flow often requires the account owner on another device. "
            'Consider {"op":"request_human",...} if automation cannot proceed.\n'
        )
    return ""


def _google_birthday_screen_hint(items: list[dict[str, Any]], url: str) -> str:
    """Google signup birthday/gender: steer away from re-filling day when Gender is still unset."""
    if "birthdaygender" not in url.lower():
        return ""
    for it in items:
        if str(it.get("role", "")).strip().lower() != "combobox":
            continue
        tx = str(it.get("text", "")).strip()
        if tx == "Gender":
            return (
                '\nNOTE: You are on Google birthday/gender. If Day and Year already show values in the list, do NOT fill '
                'them again. Gender is still unset (`text` is exactly "Gender"): open it if needed, then '
                '`{"op":"pick_option","label":"Female"}` (or Male / Rather not say / Custom), then click Next.\n'
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


def _gmail_username_screen_hint(title: str, url: str) -> str:
    """Gmail address step: reduce generic-name loops."""
    tl = (title or "").lower()
    ul = url.lower()
    if "signup/username" not in ul and "how you'll sign in" not in tl:
        return ""
    return (
        "\nNOTE: Gmail usernames are globally unique. Avoid generic words like `newusername`. "
        "Use a distinctive local part (e.g. first initial + last name + random digits). "
        "If the screenshot shows a red \"taken\" error, pick a new string before clicking Next again.\n"
    )


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
                "Use click on the Next/Continue/Submit button (often tag=button with text like Next in the list), "
                "or fill a different empty field, or press Enter after focusing the form.\n"
            )
    return ""


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
    and sends it to the planner with the text prompt. Vision is skipped if *artifacts_dir*
    is omitted (nothing to attach).
    """
    errors: list[str] = []
    recorded: list[PlaybookStep] = []
    completed = False
    final_summary: str | None = None
    last_turn = 0
    last_executed_action: dict[str, Any] | None = None

    if artifacts_dir is not None:
        artifacts_dir.mkdir(parents=True, exist_ok=True)

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
        last_nav_key = nav_key
        try:
            title = page.title()
        except Exception:
            title = ""

        err_tail = ""
        if errors:
            err_tail = "\nRecent errors (fix or work around):\n" + "\n".join(f"- {e}" for e in errors[-6:])

        stuck_hint = _stuck_fill_hint(items, last_executed_action)
        listbox_hint = _listbox_open_hint(items)
        month_done_hint = _birthday_month_committed_hint(items)
        wall_hint = _human_wall_page_hint(title, snap_url)
        google_bday_hint = _google_birthday_screen_hint(items, snap_url)
        pwd_pair_hint = _password_screen_hint(items, title, snap_url, last_executed_action)
        gmail_user_hint = _gmail_username_screen_hint(title, snap_url)
        create_email_hint = _google_create_email_choice_hint(title, snap_url, items)

        user_block = (
            f"USER_GOAL:\n{goal}\n\n"
            + snapshot_prompt_block(items, snap_url, title)
            + stuck_hint
            + listbox_hint
            + month_done_hint
            + google_bday_hint
            + pwd_pair_hint
            + gmail_user_hint
            + create_email_hint
            + wall_hint
            + err_tail
            + '\n\nReturn JSON with "thought" and "action".'
        )

        vision_path: Path | None = None
        if artifacts_dir is not None and use_vision:
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
                if write_step_png(page, artifacts_dir, turn) is None:
                    errors.append(f"turn {turn}: screenshot failed")
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
                if write_step_png(page, artifacts_dir, turn) is None:
                    errors.append(f"turn {turn}: screenshot failed")
            continue

        pb_step: PlaybookStep | None = None
        cont = True
        err: str | None = None
        execute_exception: str | None = None
        try:
            cont, pb_step, err = run_planner_action(page, action, vision_png_path=vision_path)
        except Exception as exc:  # noqa: BLE001
            execute_exception = str(exc)
            errors.append(f"turn {turn}: execute:{exc}")

        if err:
            errors.append(f"turn {turn}: {err}")

        shot_path: Path | None = None
        if artifacts_dir is not None:
            shot_path = write_step_png(page, artifacts_dir, turn)
            if shot_path is None:
                errors.append(f"turn {turn}: screenshot failed")

        if pb_step is not None:
            if shot_path is not None:
                pb_step.screenshot_after = _screenshot_relpath(playbook_out, shot_path)
            recorded.append(pb_step)

        if artifacts_dir is not None:
            exec_doc: dict[str, Any] = {
                "continue_loop": cont,
                "executor_message": err,
                "execute_exception": execute_exception,
                "screenshot_after": str(shot_path) if shot_path else None,
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
