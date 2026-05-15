from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from playwright.sync_api import Page


def write_vision_input_png(page: Page, artifacts_dir: Path, step_index: int) -> Path | None:
    """Save ``{index:03d}-vision-input.png`` — page state before the planner call (for multimodal LLM)."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    path = artifacts_dir / f"{step_index:03d}-vision-input.png"
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception:  # noqa: BLE001
        # full_page can fail on complex layouts; fallback to viewport only.
        try:
            page.screenshot(path=str(path), full_page=False)
        except Exception:  # noqa: BLE001
            return None
    return path


def write_dom_input_yaml(artifacts_dir: Path, step_index: int, doc: dict[str, Any]) -> Path:
    """Save ``{index:03d}-dom-input.yaml`` — structured DOM/a11y extraction before the planner call."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    path = artifacts_dir / f"{step_index:03d}-dom-input.yaml"
    out = {"kind": "darwin_core.agents.web_dom_input", "turn": step_index, **doc}
    path.write_text(
        yaml.safe_dump(out, sort_keys=False, allow_unicode=True, default_flow_style=False, width=120),
        encoding="utf-8",
    )
    return path
