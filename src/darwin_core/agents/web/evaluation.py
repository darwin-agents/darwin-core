from __future__ import annotations

import json

from darwin_core.services.llm.openrouter import OpenRouterService

from .prompts import RESULT_SYSTEM_PROMPT


def evaluate_run(
    service: OpenRouterService,
    goal: str,
    final_snapshot: dict[str, object],
    history: list[dict[str, object]],
) -> dict[str, object]:
    prompt = (
        f"Goal: {goal}\n"
        f"Final page snapshot: {json.dumps(final_snapshot)}\n"
        f"Action history: {json.dumps(history)}\n"
        "Return final evaluation JSON."
    )
    raw = service.chat(prompt, system_prompt=RESULT_SYSTEM_PROMPT)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Model returned non-JSON final result: {raw}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Final result payload must be a JSON object.")
    return result

