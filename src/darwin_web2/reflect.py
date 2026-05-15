"""Optional second LLM pass when verify reports problems (DARWIN_WEB2_REFLECT=1)."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Protocol

from darwin_web2.coerce import coerce_planner_raw
from darwin_web2.policy import REFLECT_SYSTEM_PROMPT


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
    user = (
        f"USER_GOAL:\n{goal}\n"
        f"{extra}\n"
        f"LATEST_OBSERVATION:\n{observation_text}\n\n"
        f"LAST_ACTION_JSON:\n{last_action}\n\n"
        f"VERIFY_MESSAGES:\n"
        + "\n".join(f"- {m}" for m in verify_messages)
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
    return raw
