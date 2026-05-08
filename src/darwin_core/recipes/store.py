from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def normalize_goal_to_task_key(goal: str) -> str:
    normalized = goal.strip().lower()
    normalized = re.sub(r"https?://\S+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "task"


def extract_domain(value: str) -> str | None:
    candidate = value.strip()
    if not candidate:
        return None
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    domain = parsed.netloc.lower()
    if not domain:
        return None
    if domain.startswith("www."):
        return domain[4:]
    return domain


def sanitize_segment(segment: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", segment.lower()).strip("-") or "unknown"


def recipe_store_dir(base_dir: Path, task_key: str, domain: str) -> Path:
    return base_dir / sanitize_segment(domain) / sanitize_segment(task_key)


def recipe_file_path(base_dir: Path, task_key: str, domain: str, version: int) -> Path:
    return recipe_store_dir(base_dir, task_key, domain) / f"v{version:04d}.json"


def parse_recipe_version(file_path: Path) -> int:
    match = re.match(r"v(\d+)\.json$", file_path.name)
    if not match:
        raise ValueError(f"Invalid recipe filename: {file_path.name}")
    return int(match.group(1))


def load_recipe(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Recipe file must contain JSON object: {path}")
    return data


def list_recipe_files(base_dir: Path, task_key: str, domain: str) -> list[Path]:
    directory = recipe_store_dir(base_dir, task_key, domain)
    if not directory.exists():
        return []
    return sorted(directory.glob("v*.json"))


def load_matching_recipes(base_dir: Path, task_key: str, domain: str) -> list[tuple[Path, dict[str, Any]]]:
    recipe_files = list_recipe_files(base_dir, task_key, domain)
    recipes = [(path, load_recipe(path)) for path in recipe_files]
    return sorted(recipes, key=lambda item: int(item[1].get("version", 0)), reverse=True)


def next_recipe_version(base_dir: Path, task_key: str, domain: str) -> int:
    recipe_files = list_recipe_files(base_dir, task_key, domain)
    if not recipe_files:
        return 1
    return max(parse_recipe_version(path) for path in recipe_files) + 1


def ensure_signal_schema(recipe: dict[str, Any], key: str) -> None:
    signals = recipe.setdefault(key, {})
    if not isinstance(signals, dict):
        recipe[key] = {}
        signals = recipe[key]
    for signal_key in ("url_contains", "title_contains", "body_contains"):
        value = signals.setdefault(signal_key, [])
        if not isinstance(value, list):
            signals[signal_key] = []


def save_recipe(
    *,
    base_dir: Path,
    task_key: str,
    domain: str,
    steps: list[dict[str, Any]],
    source_run: dict[str, Any],
    success_signals: dict[str, list[str]] | None = None,
    failure_signals: dict[str, list[str]] | None = None,
) -> Path:
    version = next_recipe_version(base_dir, task_key, domain)
    path = recipe_file_path(base_dir, task_key, domain, version)
    path.parent.mkdir(parents=True, exist_ok=True)

    recipe: dict[str, Any] = {
        "task_key": task_key,
        "domain": domain,
        "version": version,
        "created_at": utc_now_iso(),
        "last_seen_at": utc_now_iso(),
        "last_outcome": "unknown",
        "success_count": 0,
        "failure_count": 0,
        "steps": steps,
        "input_vars": [],
        "success_signals": success_signals or {},
        "failure_signals": failure_signals or {},
        "source_run": source_run,
    }
    ensure_signal_schema(recipe, "success_signals")
    ensure_signal_schema(recipe, "failure_signals")
    path.write_text(json.dumps(recipe, indent=2), encoding="utf-8")
    return path


def record_recipe_outcome(path: Path, outcome: str) -> None:
    recipe = load_recipe(path)
    recipe["last_seen_at"] = utc_now_iso()
    recipe["last_outcome"] = outcome
    if outcome == "success":
        recipe["success_count"] = int(recipe.get("success_count", 0)) + 1
    elif outcome == "failed":
        recipe["failure_count"] = int(recipe.get("failure_count", 0)) + 1
    path.write_text(json.dumps(recipe, indent=2), encoding="utf-8")


def resolve_match_domain(
    *,
    goal: str,
    current_url: str,
    recipes_root: Path,
    task_key: str,
) -> str | None:
    goal_domain = extract_domain(goal)
    if goal_domain:
        return goal_domain

    current_domain = extract_domain(current_url)
    if current_domain:
        return current_domain

    # If goal has no explicit domain, only use a stored domain when unique.
    domain_dirs = [entry.name for entry in recipes_root.iterdir()] if recipes_root.exists() else []
    matched_domains: list[str] = []
    for domain in domain_dirs:
        if recipe_store_dir(recipes_root, task_key, domain).exists():
            matched_domains.append(domain)
    if len(matched_domains) == 1:
        return matched_domains[0]
    return None

