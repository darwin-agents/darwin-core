from __future__ import annotations

from pathlib import Path

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
