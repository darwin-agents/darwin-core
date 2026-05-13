from __future__ import annotations

from pathlib import Path

import yaml

from darwin_web.playbook import Playbook, PlaybookStep


def test_playbook_yaml_roundtrip(tmp_path: Path) -> None:
    pb = Playbook(
        goal="open example",
        steps=[
            PlaybookStep(
                op="goto",
                description="Open the example.com home page",
                dom={"url": "https://example.com"},
                url="https://example.com",
            ),
            PlaybookStep(
                op="click",
                description="Follow the first link",
                dom={"selector": "a", "tag": "a"},
                selector="a",
                screenshot_after="001-step.png",
            ),
            PlaybookStep(op="wait_ms", description="Brief settle", dom={"ms": 100}, ms=100),
        ],
        final_summary="ok",
    )
    path = tmp_path / "recipe.yaml"
    pb.write(path)
    loaded = Playbook.read(path)
    assert loaded.goal == pb.goal
    assert len(loaded.steps) == 3
    assert loaded.steps[0].op == "goto"
    assert loaded.steps[0].url == "https://example.com"
    assert loaded.steps[0].description.startswith("Open")
    assert loaded.steps[1].screenshot_after == "001-step.png"
    assert loaded.final_summary == "ok"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["recipe_version"] == 1
    assert raw["steps"][1]["dom"]["tag"] == "a"


def test_playbook_yaml_select_option_roundtrip(tmp_path: Path) -> None:
    pb = Playbook(
        goal="form",
        steps=[
            PlaybookStep(
                op="select_option",
                description="Choose month",
                dom={"selector": "#m", "tag": "select"},
                selector="#m",
                value="1",
            )
        ],
    )
    path = tmp_path / "r.yaml"
    pb.write(path)
    loaded = Playbook.read(path)
    assert loaded.steps[0].op == "select_option"
    assert loaded.steps[0].value == "1"


def test_playbook_yaml_pick_option_roundtrip(tmp_path: Path) -> None:
    pb = Playbook(
        goal="signup",
        steps=[
            PlaybookStep(
                op="pick_option",
                description="Choose January from month list",
                dom={"option_label": "January"},
                selector=None,
                value="January",
            )
        ],
    )
    path = tmp_path / "pick.yaml"
    pb.write(path)
    loaded = Playbook.read(path)
    assert loaded.steps[0].op == "pick_option"
    assert loaded.steps[0].value == "January"
    assert loaded.steps[0].selector is None
