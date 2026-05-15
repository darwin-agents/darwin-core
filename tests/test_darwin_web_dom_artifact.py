from __future__ import annotations

from pathlib import Path

from darwin_web.step_screenshots import write_dom_input_yaml
from darwin_web2.observation import Observation


def test_write_dom_input_yaml_roundtrip(tmp_path: Path) -> None:
    obs = Observation(
        url="https://signup.live.com/",
        title="Agregar algunos detalles",
        items=[{"ref": 1, "tag": "button", "role": "combobox", "text": "", "value": ""}],
        alert_digest="Escriba su fecha de nacimiento.",
        fingerprint="abc123",
        layout_fingerprint="abc123",
        element_count=1,
        aria_snapshot="- combobox \"Día\":\n  - option \"19\"",
        form_html="<div class=\"form\">...</motion.div>",
        prompt_item_limit=128,
    )
    path = write_dom_input_yaml(tmp_path, 9, obs.to_dom_artifact())
    assert path.name == "009-dom-input.yaml"
    text = path.read_text(encoding="utf-8")
    assert "darwin_web2_dom_input" in text
    assert "aria_snapshot" in text
    assert "interactive_elements" in text
    assert "turn: 9" in text or "turn: 9\n" in text


def test_observation_prompt_includes_aria_when_present() -> None:
    obs = Observation(
        url="https://example.com",
        title="T",
        items=[],
        alert_digest="",
        fingerprint="fp",
        layout_fingerprint="fp",
        element_count=0,
        aria_snapshot="- button \"Next\"",
    )
    block = obs.to_prompt_block()
    assert "Accessibility tree" in block
    assert "button \"Next\"" in block
