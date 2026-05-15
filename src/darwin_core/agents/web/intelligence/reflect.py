"""Optional second LLM pass when verify reports problems (DARWIN_WEB2_REFLECT=1)."""

from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any, Protocol

from darwin_core.agents.web.execution.coerce import coerce_planner_raw
from darwin_core.agents.web.core.policy import REFLECT_SYSTEM_PROMPT


class _ReflectLLM(Protocol):
    def chat_json(self, user_prompt: str, *, system_prompt: str) -> dict[str, Any]: ...

    def chat_planner_turn(
        self,
        user_prompt: str,
        *,
        system_prompt: str,
        vision_png_path: Path | None = None,
    ) -> Any: ...


def reflect_enabled() -> bool:
    v = os.getenv("DARWIN_WEB2_REFLECT", "").strip().lower()
    return v in ("1", "true", "yes", "on")


_REPEATED_CLICK_RE = re.compile(r"repeated \w+ on ref (\d+)", re.IGNORECASE)


def _blocked_click_ref(verify_messages: tuple[str, ...]) -> int | None:
    for msg in verify_messages:
        m = _REPEATED_CLICK_RE.search(msg)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def _force_different_from_repeated_click(
    raw: dict[str, Any],
    *,
    last_action: dict[str, Any],
    blocked_ref: int,
) -> dict[str, Any]:
    """If reflect repeats the same click ref, substitute a short settle wait."""
    act = raw.get("action")
    if not isinstance(act, dict):
        return raw
    if act.get("op") != "click":
        return raw
    try:
        ref = int(act.get("ref"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return raw
    last_ref = last_action.get("ref")
    try:
        last_ref_i = int(last_ref) if last_ref is not None else None
    except (TypeError, ValueError):
        last_ref_i = None
    if ref != blocked_ref and ref != last_ref_i:
        return raw
    out = copy.deepcopy(raw)
    out["thought"] = (
        str(out.get("thought", "")).strip()
        + " (reflect: avoid repeating click on stuck ref; wait for UI)"
    ).strip()
    out["action"] = {
        "op": "wait_ms",
        "ms": 600,
        "describe": f"reflect: settle UI instead of clicking ref {ref} again",
    }
    return out


def reflect_repair_action(
    *,
    llm: _ReflectLLM,
    goal: str,
    observation_text: str,
    last_action: dict[str, Any],
    verify_messages: tuple[str, ...],
    vision_png_path: Path | None = None,
    goal_context: str = "",
) -> dict[str, Any] | None:
    """Ask for a single replacement action; returns parsed dict with thought+action or None."""
    if not verify_messages:
        return None
    extra = f"\n{goal_context}\n" if goal_context.strip() else ""
    blocked_ref = _blocked_click_ref(verify_messages)
    repeat_rule = ""
    if blocked_ref is not None:
        repeat_rule = (
            f"\nCRITICAL: Verification reports repeated click on ref {blocked_ref}. "
            f"Do NOT use click on ref {blocked_ref} again — pick a different op/ref "
            "(submit, combobox_pick, fill another field, wait_ms, request_human).\n"
        )
    user = (
        f"USER_GOAL:\n{goal}\n"
        f"{extra}\n"
        f"LATEST_OBSERVATION:\n{observation_text}\n\n"
        f"LAST_ACTION_JSON:\n{last_action}\n\n"
        f"VERIFY_MESSAGES:\n"
        + "\n".join(f"- {m}" for m in verify_messages)
        + repeat_rule
        + "\n\nReturn JSON with thought and action."
    )
    try:
        if vision_png_path is not None and vision_png_path.is_file():
            transcript = llm.chat_planner_turn(
                user,
                system_prompt=REFLECT_SYSTEM_PROMPT,
                vision_png_path=vision_png_path,
            )
            raw = dict(transcript.assistant_parsed)
        else:
            raw = llm.chat_json(user, system_prompt=REFLECT_SYSTEM_PROMPT)
    except (ValueError, RuntimeError):
        return None
    if not isinstance(raw, dict):
        return None
    raw = coerce_planner_raw(copy.deepcopy(raw))
    act = raw.get("action")
    if not isinstance(act, dict) or not isinstance(act.get("op"), str):
        return None
    if blocked_ref is not None:
        raw = _force_different_from_repeated_click(
            raw, last_action=last_action, blocked_ref=blocked_ref
        )
    return raw
