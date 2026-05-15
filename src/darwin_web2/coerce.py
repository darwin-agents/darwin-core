"""Normalize common malformed planner JSON shapes."""

from __future__ import annotations

from typing import Any


def coerce_planner_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """Fix ``action`` as list, nested op dicts, or steps under other keys."""
    _KNOWN_OPS = frozenset({
        "goto", "go_back", "click", "fill", "select_option", "pick_option",
        "combobox_pick", "press", "wait_ms", "scroll_into_view", "request_human", "done",
    })
    action = raw.get("action")
    if isinstance(action, dict) and action.get("op") is None:
        # Pattern 1: {"action": {"fill": {"op": "fill", "ref": 6, ...}}}
        # The child dict has "op" — just lift it.
        for _k, v in action.items():
            if isinstance(v, dict) and isinstance(v.get("op"), str):
                raw["action"] = v
                action = v
                break
        else:
            # Pattern 2: {"action": {"request_human": {"reason": "...", ...}}}
            # The key IS the op name, the value is the params dict (no "op" inside).
            for k, v in action.items():
                if k in _KNOWN_OPS and isinstance(v, dict):
                    raw["action"] = {"op": k, **v}
                    action = raw["action"]
                    break
                # Pattern 3: {"action": {"request_human": true/string}}
                # Single-key shorthand with a non-dict value.
                if k in _KNOWN_OPS and not isinstance(v, dict):
                    raw["action"] = {"op": k}
                    action = raw["action"]
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
    action = raw.get("action")
    if isinstance(action, dict) and action.get("op") == "fill_input":
        action["op"] = "fill"
        if "value" not in action:
            for alt in ("text", "input", "content"):
                v = action.get(alt)
                if isinstance(v, str):
                    action["value"] = v
                    break
    return raw
