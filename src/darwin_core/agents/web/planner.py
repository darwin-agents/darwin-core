from __future__ import annotations

import json

from darwin_core.services.llm.openrouter import OpenRouterService

from .prompts import SYSTEM_PROMPT


def choose_action(
    service: OpenRouterService,
    goal: str,
    step: int,
    snapshot: dict[str, object],
    recent_errors: list[str],
) -> tuple[dict[str, object], str, str]:
    prompt = (
        f"Goal: {goal}\n"
        f"Step: {step}\n"
        f"Current page snapshot JSON:\n{json.dumps(snapshot)}\n"
        f"Recent execution errors:\n{json.dumps(recent_errors)}\n"
        "Checklist: if page asks for birthday/gender, ensure month/day/year/gender are addressed before Next.\n"
        "Return the next single action."
    )
    raw = service.chat(prompt, system_prompt=SYSTEM_PROMPT)
    try:
        action = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Model returned non-JSON action: {raw}") from exc
    if not isinstance(action, dict):
        raise RuntimeError("Model action payload must be a JSON object.")
    return action, prompt, raw

