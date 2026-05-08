from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .action_runtime import run_action

if TYPE_CHECKING:
    from playwright.sync_api import Page


def write_debug_artifact(
    *,
    artifacts_dir: Path,
    step: int,
    suffix: str,
    payload: Any,
) -> None:
    path = artifacts_dir / f"step-{step:03d}-{suffix}"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
        return
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def execute_action_step(
    *,
    page: Page,
    action: dict[str, Any],
    step_number: int,
    artifacts_dir: Path,
    action_history: list[dict[str, Any]],
    error_history: list[str],
    debug_steps: bool = False,
) -> bool:
    print(json.dumps({"step": step_number, "action": action}, ensure_ascii=True))
    error: str | None = None
    try:
        should_continue = run_action(page, action)
    except Exception as exc:  # noqa: BLE001
        should_continue = True
        error = str(exc)
        error_history.append(error)

    shot_path = artifacts_dir / f"step-{step_number:03d}.png"
    try:
        page.screenshot(path=str(shot_path), full_page=True)
    except Exception:  # noqa: BLE001
        shot_path = Path("")

    action_history.append(
        {
            "step": step_number,
            "action": action,
            "url_after": page.url,
            "title_after": page.title(),
            "error": error,
            "screenshot": str(shot_path) if str(shot_path) else None,
        }
    )
    if debug_steps:
        write_debug_artifact(
            artifacts_dir=artifacts_dir,
            step=step_number,
            suffix="execution.json",
            payload=action_history[-1],
        )
    return should_continue

