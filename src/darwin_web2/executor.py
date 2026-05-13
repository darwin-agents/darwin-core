"""Thin re-exports of the proven Playwright executor (shared with darwin_web)."""

from __future__ import annotations

from darwin_web.executor import replay_playbook, replay_step, run_planner_action

__all__ = ["run_planner_action", "replay_playbook", "replay_step"]
