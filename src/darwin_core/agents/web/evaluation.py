"""LLM-driven evaluation of a finished browser-automation run.

The evaluator receives the original goal, the final page snapshot, and the
full action history, then asks the configured model to produce a structured
JSON verdict describing whether the goal was achieved.

The public entry point is :func:`evaluate_run`. The helpers below are private
and only exist to keep the orchestration small, readable, and individually
testable.
"""

from __future__ import annotations

import json
from typing import Final

from darwin_core.services.llm.openrouter import OpenRouterService

from .prompts import RESULT_SYSTEM_PROMPT

__all__ = ["evaluate_run"]


# Upper bound on the slice of the raw model response that we surface in error
# messages. Final evaluations occasionally produce very long bodies and
# embedding the entire payload would make logs unusable.
_MAX_RAW_PREVIEW: Final[int] = 2000


def _safe_json_dumps(payload: object) -> str:
    """Serialize ``payload`` to JSON, coercing unknown types to strings.

    Snapshots and action history originate in the browser layer and may
    contain values that are not natively JSON-serializable (e.g. ``Path``
    instances or exception objects collected during a failed step). Falling
    back to ``str`` keeps prompt construction infallible while still giving
    the evaluator readable context.
    """
    return json.dumps(payload, default=str)


def _build_evaluation_prompt(
    goal: str,
    final_snapshot: dict[str, object],
    history: list[dict[str, object]],
) -> str:
    """Compose the user message sent to the evaluator model.

    The layout intentionally mirrors what the planner submits during the run
    so the model sees familiar context: a goal line, the final page snapshot,
    and the full action history, all rendered as JSON.
    """
    return (
        f"Goal: {goal}\n"
        f"Final page snapshot: {_safe_json_dumps(final_snapshot)}\n"
        f"Action history: {_safe_json_dumps(history)}\n"
        "Return final evaluation JSON."
    )


def _strip_code_fences(raw: str) -> str:
    """Drop a single pair of Markdown code fences if the model added them.

    The system prompt forbids Markdown, but some models still wrap the JSON
    in ``` or ```json fences. We strip one matching pair at the very start
    and end (after trimming whitespace) so the JSON decoder gets clean input.
    Anything that does not look like a fenced block is returned unchanged.
    """
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        newline_index = cleaned.find("\n")
        cleaned = cleaned[newline_index + 1 :] if newline_index != -1 else cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def _preview(raw: str) -> str:
    """Return a length-bounded snippet of ``raw`` for use in error messages."""
    if len(raw) <= _MAX_RAW_PREVIEW:
        return raw
    return f"{raw[:_MAX_RAW_PREVIEW]}…[truncated]"


def _parse_evaluation_payload(raw: str) -> dict[str, object]:
    """Decode the model response into a JSON object.

    Raises :class:`RuntimeError` when the response is empty, not valid JSON,
    or not a JSON object. The error message includes a bounded preview of the
    raw response so logs remain actionable without exploding in size.
    """
    if not raw or not raw.strip():
        raise RuntimeError("Model returned an empty evaluation response.")

    cleaned = _strip_code_fences(raw)
    if not cleaned:
        raise RuntimeError(f"Model returned no JSON content: {_preview(raw)}")

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Model returned non-JSON final result: {_preview(raw)}") from exc

    if not isinstance(result, dict):
        raise RuntimeError(
            "Final result payload must be a JSON object, "
            f"got {type(result).__name__}: {_preview(raw)}"
        )
    return result


def evaluate_run(
    service: OpenRouterService,
    goal: str,
    final_snapshot: dict[str, object],
    history: list[dict[str, object]],
) -> dict[str, object]:
    """Ask the configured LLM to judge whether ``goal`` was achieved.

    Builds a prompt from the final snapshot and action history, dispatches the
    request through ``service``, and returns the parsed JSON verdict. The
    caller is expected to fill in defaults for any fields it requires that
    the model may have omitted (see ``runner.main`` for the canonical usage).

    Parameters
    ----------
    service:
        OpenRouter client used to issue the chat completion.
    goal:
        Natural-language description of the run target. Must be non-empty.
    final_snapshot:
        Snapshot of the final page state (URL, title, controls, ...).
    history:
        Sequence of executed actions and any errors collected during the run.

    Returns
    -------
    dict[str, object]
        The parsed JSON object returned by the evaluator.

    Raises
    ------
    ValueError
        If ``goal`` is empty or whitespace, or if ``final_snapshot`` / ``history``
        have unexpected top-level types.
    RuntimeError
        If the model response cannot be decoded into a JSON object.
    """
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("evaluate_run requires a non-empty goal string.")
    if not isinstance(final_snapshot, dict):
        raise ValueError("evaluate_run requires final_snapshot to be a dict.")
    if not isinstance(history, list):
        raise ValueError("evaluate_run requires history to be a list.")

    prompt = _build_evaluation_prompt(goal, final_snapshot, history)
    raw = service.chat(prompt, system_prompt=RESULT_SYSTEM_PROMPT)
    return _parse_evaluation_payload(raw)
