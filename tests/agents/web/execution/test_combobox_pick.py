from __future__ import annotations

from darwin_core.agents.web.execution.executor import _label_pick_variants
from darwin_core.agents.web.execution.coerce import coerce_planner_raw


def test_label_pick_variants_includes_spanish_month() -> None:
    variants = _label_pick_variants("December")
    assert "Diciembre" in variants or "diciembre" in variants


def test_coerce_fill_input_to_fill() -> None:
    raw = {"thought": "x", "action": {"op": "fill_input", "ref": 5, "text": "1991"}}
    out = coerce_planner_raw(raw)
    assert out["action"]["op"] == "fill"
    assert out["action"]["value"] == "1991"


def test_coerce_combobox_pick_op() -> None:
    raw = {
        "thought": "pick day",
        "action": {"combobox_pick": {"ref": 3, "label": "19"}},
    }
    out = coerce_planner_raw(raw)
    assert out["action"]["op"] == "combobox_pick"
    assert out["action"]["label"] == "19"
