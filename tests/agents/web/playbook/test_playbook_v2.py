from __future__ import annotations

from pathlib import Path

import yaml

from darwin_core.agents.web.playbook.playbook import PlaybookStep

from darwin_core.agents.web.playbook.playbook import AnnotatedStep, PlaybookV2, goal_fingerprint


def test_goal_fingerprint_ignores_query_string() -> None:
    g = "Open Gmail"
    a = goal_fingerprint(g, "https://accounts.google.com/foo?x=1")
    b = goal_fingerprint(g, "https://accounts.google.com/foo?y=2")
    assert a == b


def test_playbook_v2_roundtrip(tmp_path: Path) -> None:
    step = PlaybookStep(
        op="wait_ms",
        description="noop",
        ms=1,
    )
    pb = PlaybookV2(
        goal="test goal",
        steps=[AnnotatedStep(step, step_id="s1", semantic="noop")],
        goal_fingerprint="abc123",
    )
    path = tmp_path / "pb.yaml"
    pb.write(path)
    loaded = PlaybookV2.read(path)
    assert loaded.goal == pb.goal
    assert loaded.recipe_version == 2
    assert loaded.steps[0].step_id == "s1"
    assert loaded.steps[0].semantic == "noop"
    assert loaded.steps[0].step.op == "wait_ms"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["steps"][0]["id"] == "s1"
