"""Playbook v2: versioned recipes with optional step ids / semantics for repair workflows.

Also contains the v1 PlaybookStep / Playbook classes (migrated from darwin_web) so that
darwin_core.agents.web is self-contained and darwin_web can be removed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml


# ---------------------------------------------------------------------------
# v1 primitives (migrated from darwin_web.playbook)
# ---------------------------------------------------------------------------

PlaybookOp = Literal[
    "goto",
    "go_back",
    "click",
    "fill",
    "select_option",
    "pick_option",
    "press",
    "wait_ms",
    "scroll_into_view",
]


@dataclass
class PlaybookStep:
    """One reproducible recipe step: human description + DOM + machine fields."""

    op: PlaybookOp
    description: str
    # DOM context for humans and for debugging replay (selector is authoritative for ops).
    dom: dict[str, Any] | None = None
    screenshot_after: str | None = None
    url: str | None = None
    selector: str | None = None
    value: str | None = None
    clear_first: bool = True
    key: str | None = None
    ms: int | None = None

    def to_recipe_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"description": self.description, "op": self.op}
        if self.dom:
            d["dom"] = self.dom
        if self.screenshot_after:
            d["screenshot_after"] = self.screenshot_after
        if self.url is not None:
            d["url"] = self.url
        if self.selector is not None:
            d["selector"] = self.selector
        if self.value is not None:
            d["value"] = self.value
        if self.op == "fill":
            d["clear_first"] = self.clear_first
        if self.key is not None:
            d["key"] = self.key
        if self.ms is not None:
            d["ms"] = self.ms
        return d

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> PlaybookStep:
        op = raw.get("op")
        if op not in (
            "goto",
            "go_back",
            "click",
            "fill",
            "select_option",
            "pick_option",
            "press",
            "wait_ms",
            "scroll_into_view",
        ):
            raise ValueError(f"invalid playbook op: {op!r}")
        dom = raw.get("dom")
        if dom is not None and not isinstance(dom, dict):
            raise ValueError("dom must be a mapping or omitted")
        if op == "pick_option":
            val = raw.get("value")
            if not isinstance(val, str) or not val.strip():
                raise ValueError("pick_option requires non-empty string value (visible option label)")
        return PlaybookStep(
            op=op,  # type: ignore[arg-type]
            description=str(raw.get("description") or "").strip() or "(no description)",
            dom=dict(dom) if isinstance(dom, dict) else None,
            screenshot_after=raw.get("screenshot_after"),
            url=raw.get("url"),
            selector=raw.get("selector"),
            value=raw.get("value"),
            clear_first=bool(raw.get("clear_first", True)),
            key=raw.get("key"),
            ms=raw.get("ms"),
        )


@dataclass
class Playbook:
    """YAML recipe v1: goal, metadata, ordered steps with DOM instructions."""

    goal: str
    steps: list[PlaybookStep] = field(default_factory=list)
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    final_summary: str | None = None

    def to_recipe_document(self) -> dict[str, Any]:
        return {
            "recipe_version": self.version,
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
    def read(path: Path) -> Playbook:
        raw_text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            data = json.loads(raw_text)
        else:
            data = yaml.safe_load(raw_text)
        if not isinstance(data, dict):
            raise ValueError("playbook must be a mapping")
        steps_raw = data.get("steps") or []
        if not isinstance(steps_raw, list):
            raise ValueError("steps must be a list")
        steps = [PlaybookStep.from_dict(s) for s in steps_raw if isinstance(s, dict)]
        ver = data.get("recipe_version", data.get("version", 1))
        return Playbook(
            goal=str(data.get("goal", "")),
            steps=steps,
            version=int(ver) if ver is not None else 1,
            created_at=str(data.get("created_at", "")),
            final_summary=data.get("final_summary"),
        )


# ---------------------------------------------------------------------------
# v2 types
# ---------------------------------------------------------------------------



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
