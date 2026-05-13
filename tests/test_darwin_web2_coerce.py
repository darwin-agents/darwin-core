from __future__ import annotations

from darwin_web2.coerce import coerce_planner_raw


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
