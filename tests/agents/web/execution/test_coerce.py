from __future__ import annotations

from darwin_core.agents.web.execution.coerce import coerce_planner_raw


def test_coerce_fill_key_without_inner_op() -> None:
    raw: dict = {
        "thought": "t",
        "action": {"fill": {"ref": 1, "value": "x", "clear_first": True, "describe": "d"}},
    }
    coerce_planner_raw(raw)
    assert raw["action"]["op"] == "fill"
    assert raw["action"]["ref"] == 1


def test_coerce_nested_action() -> None:
    raw: dict = {
        "thought": "t",
        "action": {
            "fill": {
                "op": "fill",
                "ref": 1,
                "value": "x",
                "clear_first": True,
                "describe": "d",
            }
        },
    }
    coerce_planner_raw(raw)
    assert raw["action"]["op"] == "fill"
