from __future__ import annotations

from pathlib import Path

from darwin_core.openrouter_web_agent import recipe_considered_success
from darwin_core.recipes.store import (
    load_matching_recipes,
    normalize_goal_to_task_key,
    record_recipe_outcome,
    save_recipe,
)


def test_normalize_goal_to_task_key() -> None:
    assert normalize_goal_to_task_key("open a gmail account") == "open-a-gmail-account"
    assert (
        normalize_goal_to_task_key("Open https://accounts.google.com/signup a Gmail account")
        == "open-a-gmail-account"
    )


def test_recipe_versions_are_sorted_desc(tmp_path: Path) -> None:
    save_recipe(
        base_dir=tmp_path,
        task_key="open-a-gmail-account",
        domain="accounts.google.com",
        steps=[{"action": "goto", "url": "https://accounts.google.com/signup"}],
        source_run={"goal": "open a gmail account"},
    )
    save_recipe(
        base_dir=tmp_path,
        task_key="open-a-gmail-account",
        domain="accounts.google.com",
        steps=[{"action": "goto", "url": "https://accounts.google.com/signup"}],
        source_run={"goal": "open a gmail account"},
    )

    recipes = load_matching_recipes(tmp_path, "open-a-gmail-account", "accounts.google.com")
    assert [recipe["version"] for _, recipe in recipes] == [2, 1]


def test_record_recipe_outcome_updates_counts(tmp_path: Path) -> None:
    recipe_path = save_recipe(
        base_dir=tmp_path,
        task_key="open-a-gmail-account",
        domain="accounts.google.com",
        steps=[{"action": "wait", "wait_ms": 100}],
        source_run={"goal": "open a gmail account"},
    )

    record_recipe_outcome(recipe_path, "failed")
    recipes = load_matching_recipes(tmp_path, "open-a-gmail-account", "accounts.google.com")
    _, recipe = recipes[0]
    assert recipe["failure_count"] == 1
    assert recipe["last_outcome"] == "failed"


def test_recipe_considered_success_with_signals() -> None:
    recipe = {
        "success_signals": {"url_contains": ["accounts.google.com"], "title_contains": ["google account"]},
        "failure_signals": {"body_contains": ["enter first name"]},
    }
    ok_snapshot = {
        "url": "https://accounts.google.com/lifecycle/steps/signup/birthdaygender",
        "title": "Create your Google Account",
        "body_text_excerpt": "Birthday and gender",
    }
    fail_snapshot = {
        "url": "https://accounts.google.com/lifecycle/steps/signup/name",
        "title": "Create your Google Account",
        "body_text_excerpt": "Enter first name",
    }

    assert recipe_considered_success(recipe, ok_snapshot)
    assert not recipe_considered_success(recipe, fail_snapshot)
