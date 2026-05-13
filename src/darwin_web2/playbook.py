"""Playbook v2: versioned recipes with optional step ids / semantics for repair workflows."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from darwin_web.playbook import PlaybookStep


def goal_fingerprint(goal: str, url: str, *, max_goal: int = 256) -> str:
    """Stable key for matching a playbook to a task + site (not locale-specific)."""
    g = re.sub(r"\s+", " ", (goal or "").strip().lower())[:max_goal]
    try:
        from urllib.parse import urlparse

        host = (urlparse(url).netloc or "").lower()
    except Exception:  # noqa: BLE001
        host = ""
    raw = f"{g}|{host}"
    import hashlib

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass
class AnnotatedStep:
    """Replayable step plus optional metadata for drift repair / analytics."""

    step: PlaybookStep
    step_id: str | None = None
    semantic: str | None = None

    def to_recipe_dict(self) -> dict[str, Any]:
        d = self.step.to_recipe_dict()
        if self.step_id:
            d["id"] = self.step_id
        if self.semantic:
            d["semantic"] = self.semantic
        return d

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> AnnotatedStep:
        d = dict(raw)
        sid = d.pop("id", None) or d.pop("step_id", None)
        sem = d.pop("semantic", None)
        return AnnotatedStep(
            PlaybookStep.from_dict(d),
            str(sid).strip() if isinstance(sid, str) and sid.strip() else None,
            str(sem).strip() if isinstance(sem, str) and sem.strip() else None,
        )


@dataclass
class PlaybookV2:
    goal: str
    steps: list[AnnotatedStep] = field(default_factory=list)
    recipe_version: int = 2
    goal_fingerprint: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    final_summary: str | None = None

    def to_recipe_document(self) -> dict[str, Any]:
        return {
            "recipe_version": self.recipe_version,
            "goal_fingerprint": self.goal_fingerprint,
            "created_at": self.created_at,
            "goal": self.goal,
            "final_summary": self.final_summary,
            "steps": [s.to_recipe_dict() for s in self.steps],
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(
            self.to_recipe_document(),
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=120,
        )
        path.write_text(text, encoding="utf-8")

    @staticmethod
    def read(path: Path) -> PlaybookV2:
        raw_text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw_text)
        if not isinstance(data, dict):
            raise ValueError("playbook must be a mapping")
        steps_raw = data.get("steps") or []
        if not isinstance(steps_raw, list):
            raise ValueError("steps must be a list")
        steps = [AnnotatedStep.from_dict(s) for s in steps_raw if isinstance(s, dict)]
        ver = int(data.get("recipe_version", data.get("version", 2)))
        gfp = str(data.get("goal_fingerprint") or "")
        return PlaybookV2(
            goal=str(data.get("goal", "")),
            steps=steps,
            recipe_version=ver,
            goal_fingerprint=gfp,
            created_at=str(data.get("created_at", "")),
            final_summary=data.get("final_summary"),
        )

    def legacy_steps(self) -> list[PlaybookStep]:
        """Steps for :func:`darwin_web.executor.replay_playbook` (metadata stripped)."""
        return [a.step for a in self.steps]
