"""Replay helpers and repair markers when a deterministic step fails."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from playwright.sync_api import Page

from darwin_web2.executor import replay_step
from darwin_web2.playbook import AnnotatedStep


def replay_annotated_steps_until_failure(
    page: Page,
    steps: list[AnnotatedStep],
    *,
    default_timeout_ms: float = 12_000,
) -> tuple[bool, int | None, str | None]:
    """Run each ``AnnotatedStep.step`` in order. Returns ``(ok, failed_index, error)``."""
    for idx, ast in enumerate(steps):
        try:
            replay_step(page, ast.step, default_timeout_ms=default_timeout_ms)
        except Exception as exc:  # noqa: BLE001
            return False, idx, str(exc)
    return True, None, None


def write_repair_marker(
    playbook_path: Path,
    *,
    failed_index: int,
    error: str,
    page_url: str = "",
) -> Path:
    """Write a sibling YAML describing replay failure (human or agent can repair playbook)."""
    out = playbook_path.with_name(playbook_path.stem + ".repair.yaml")
    doc: dict[str, Any] = {
        "kind": "darwin_web2_playbook_repair",
        "playbook": str(playbook_path),
        "failed_step_index": failed_index,
        "error": error,
        "page_url": page_url,
    }
    out.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    return out
