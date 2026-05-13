"""Playwright step execution: run one agent action, capture evidence, optional debug dumps.

Keeps the runner resilient to flaky pages (closed tabs, transient Playwright errors) so a
single bad screenshot or title read does not abort the whole run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .action_runtime import run_action
from .web_owner_profile import WebOwnerProfile

if TYPE_CHECKING:
    from playwright.sync_api import Page


def _json_dumps_safe(obj: Any) -> str:
    """Serialize *obj* to JSON; fall back if values are not JSON-native (e.g. datetime)."""
    try:
        return json.dumps(obj, indent=2, ensure_ascii=True)
    except (TypeError, ValueError):
        return json.dumps({"_serialization_fallback": repr(obj)}, indent=2, ensure_ascii=True)


def write_debug_artifact(
    *,
    artifacts_dir: Path,
    step: int,
    suffix: str,
    payload: Any,
) -> None:
    """Write a debug file under *artifacts_dir* named ``step-{step:03d}-{suffix}``.

    Strings are written as UTF-8 text. Bytes are written raw. Anything else is JSON-encoded
    with a safe fallback when values are not serializable. Failures are logged and do not
    raise, so debug output never stops the agent loop.
    """
    path = artifacts_dir / f"step-{step:03d}-{suffix}"
    try:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            json.dumps(
                {"debug_artifact_error": "mkdir_failed", "path": str(artifacts_dir), "detail": str(exc)},
                ensure_ascii=True,
            )
        )
        return
    try:
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8")
        elif isinstance(payload, (bytes, bytearray)):
            path.write_bytes(bytes(payload))
        else:
            path.write_text(_json_dumps_safe(payload), encoding="utf-8")
    except OSError as exc:
        print(
            json.dumps(
                {"debug_artifact_error": "write_failed", "path": str(path), "detail": str(exc)},
                ensure_ascii=True,
            )
        )


def _read_page_url(page: Page) -> str:
    """Return the current page URL, or empty string if the page is unusable."""
    try:
        url = page.url
        return url if isinstance(url, str) else ""
    except Exception:  # noqa: BLE001 — Playwright raises on closed/detached page
        return ""


def _read_page_title(page: Page) -> str:
    """Return document title, or empty string if navigation is in flight or page is closed."""
    try:
        title = page.title()
        return title if isinstance(title, str) else ""
    except Exception:  # noqa: BLE001
        return ""


def _screenshot_step(page: Page, artifacts_dir: Path, step_number: int) -> str | None:
    """Save a full-page PNG for this step; return absolute path string, or None on failure."""
    shot_path = artifacts_dir / f"step-{step_number:03d}.png"
    try:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shot_path), full_page=True)
    except Exception:  # noqa: BLE001 — screenshot optional for history
        return None
    return str(shot_path)


def execute_action_step(
    *,
    page: Page,
    action: dict[str, Any],
    step_number: int,
    artifacts_dir: Path,
    action_history: list[dict[str, Any]],
    error_history: list[str],
    debug_steps: bool = False,
    owner_profile: WebOwnerProfile | None = None,
) -> bool:
    """Execute one planner/recipe *action* on *page* and append a history record.

    Runs :func:`run_action` inside a broad try/except so model or DOM mistakes surface in
    *error_history* without crashing. Always records URL/title (best-effort), optional PNG,
    and whether the loop should continue (``False`` only for ``{"action": "done"}``).

    Returns:
        ``False`` when the action is ``done`` (caller should stop). ``True`` otherwise,
        including after recoverable errors so the agent can retry or fall back.
    """
    try:
        print(json.dumps({"step": step_number, "action": action}, ensure_ascii=True, default=str))
    except (TypeError, ValueError):
        print(json.dumps({"step": step_number, "action": repr(action)}, ensure_ascii=True))

    error: str | None = None
    should_continue = True

    if not isinstance(action, dict):
        err = f"action must be dict, got {type(action).__name__}"
        error_history.append(err)
        error = err
    else:
        try:
            should_continue = run_action(page, action, owner_profile=owner_profile)
        except Exception as exc:  # noqa: BLE001 — surface DOM/runtime errors to the planner
            should_continue = True
            error = str(exc)
            error_history.append(error)

    screenshot_path = _screenshot_step(page, artifacts_dir, step_number)
    action_history.append(
        {
            "step": step_number,
            "action": action if isinstance(action, dict) else {"_invalid_action": repr(action)},
            "url_after": _read_page_url(page),
            "title_after": _read_page_title(page),
            "error": error,
            "screenshot": screenshot_path,
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
