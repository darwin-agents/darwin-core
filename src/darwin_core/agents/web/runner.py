from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from darwin_core.recipes.store import (
    load_matching_recipes,
    normalize_goal_to_task_key,
    record_recipe_outcome,
    resolve_match_domain,
    save_recipe,
)
from darwin_core.services.llm.openrouter import OpenRouterService

from .action_runtime import action_signature, fallback_action
from .evaluation import evaluate_run
from .execution import execute_action_step, write_debug_artifact
from .form_actions import choose_form_actions, google_birthday_ready_to_continue
from .planner import choose_action
from .recipes import normalize_domain, recipe_considered_success
from .snapshot import page_snapshot, snapshot_signature


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenRouter-driven web agent via Browser Use CDP.")
    parser.add_argument("goal", help="High-level browsing goal for the agent.")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=int(os.getenv("OPENROUTER_WEB_MAX_STEPS", "12")),
        help="Maximum action steps before stopping.",
    )
    parser.add_argument(
        "--server-url",
        default=os.getenv("BROWSER_USE_SERVER_URL", "http://localhost:8000"),
        help="Local Darwin Browser Use server URL.",
    )
    parser.add_argument(
        "--artifacts-dir",
        default=os.getenv("OPENROUTER_WEB_ARTIFACTS_DIR", "artifacts/openrouter-web-agent"),
        help="Directory for screenshots and final run report.",
    )
    parser.add_argument(
        "--recipes-dir",
        default=os.getenv("OPENROUTER_WEB_RECIPES_DIR", "artifacts/openrouter-web-recipes"),
        help="Versioned recipe memory directory.",
    )
    parser.add_argument(
        "--debug-steps",
        action="store_true",
        help="Write per-step debug artifacts (snapshot, planner prompt/raw, chosen action, and recent errors).",
    )
    return parser


def request_cdp_url(server_url: str) -> str:
    response = httpx.post(
        f"{server_url.rstrip('/')}/browser/connect",
        json={},
        timeout=20.0,
    )
    response.raise_for_status()
    data = response.json()
    cdp_ws_url = data.get("cdp_ws_url")
    if not isinstance(cdp_ws_url, str) or not cdp_ws_url:
        raise RuntimeError("Invalid /browser/connect response; missing cdp_ws_url.")
    return cdp_ws_url


def main() -> None:
    from playwright.sync_api import sync_playwright

    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    cdp_ws_url = request_cdp_url(args.server_url)
    service = OpenRouterService()
    artifacts_dir = Path(args.artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    recipes_dir = Path(args.recipes_dir)
    recipes_dir.mkdir(parents=True, exist_ok=True)
    action_history: list[dict[str, Any]] = []
    error_history: list[str] = []
    repeated_signature_count = 0
    previous_signature: str | None = None
    previous_snapshot_signature: str | None = None
    stagnant_snapshot_count = 0
    auto_action_queue: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_ws_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()

        task_key = normalize_goal_to_task_key(args.goal)
        start_snapshot = page_snapshot(page)
        match_domain = resolve_match_domain(
            goal=args.goal,
            current_url=str(start_snapshot.get("url", "")),
            recipes_root=recipes_dir,
            task_key=task_key,
        )
        active_recipe_path: Path | None = None
        active_recipe: dict[str, Any] | None = None
        current_step = 1

        if match_domain:
            matched = load_matching_recipes(recipes_dir, task_key, match_domain)
            if matched:
                active_recipe_path, active_recipe = matched[0]
                print(
                    json.dumps(
                        {
                            "recipe_replay": {
                                "task_key": task_key,
                                "domain": match_domain,
                                "path": str(active_recipe_path),
                                "version": active_recipe.get("version"),
                            }
                        },
                        ensure_ascii=True,
                    )
                )
                recipe_steps = active_recipe.get("steps", [])
                if isinstance(recipe_steps, list):
                    for recipe_action in recipe_steps:
                        if current_step > args.max_steps:
                            break
                        if not isinstance(recipe_action, dict):
                            continue
                        should_continue = execute_action_step(
                            page=page,
                            action=recipe_action,
                            step_number=current_step,
                            artifacts_dir=artifacts_dir,
                            action_history=action_history,
                            error_history=error_history,
                            debug_steps=args.debug_steps,
                        )
                        current_step += 1
                        if not should_continue:
                            break

                snapshot_after_recipe = page_snapshot(page)
                if recipe_considered_success(active_recipe, snapshot_after_recipe):
                    record_recipe_outcome(active_recipe_path, "success")
                    final_result = {
                        "status": "success",
                        "summary": "Completed via cached recipe replay without planner fallback.",
                        "email": None,
                        "password": None,
                        "evidence": {
                            "url": snapshot_after_recipe.get("url", ""),
                            "title": snapshot_after_recipe.get("title", ""),
                        },
                        "artifacts_dir": str(artifacts_dir),
                        "steps_executed": len(action_history),
                    }
                    report_path = artifacts_dir / "run-result.json"
                    report_path.write_text(json.dumps(final_result, indent=2), encoding="utf-8")
                    print(json.dumps({"final_result": final_result, "report_path": str(report_path)}, ensure_ascii=True))
                    browser.close()
                    return
                if active_recipe_path:
                    record_recipe_outcome(active_recipe_path, "failed")

        final_snapshot: dict[str, Any] = {"url": "", "title": "", "body_text_excerpt": ""}
        for step in range(current_step, args.max_steps + 1):
            snapshot = page_snapshot(page)
            final_snapshot = snapshot
            if args.debug_steps:
                write_debug_artifact(
                    artifacts_dir=artifacts_dir,
                    step=step,
                    suffix="snapshot.json",
                    payload=snapshot,
                )
            current_snapshot_sig = snapshot_signature(snapshot)
            stagnant_snapshot_count = stagnant_snapshot_count + 1 if current_snapshot_sig == previous_snapshot_signature else 0
            previous_snapshot_signature = current_snapshot_sig

            if auto_action_queue:
                action = auto_action_queue.pop(0)
            else:
                if google_birthday_ready_to_continue(snapshot):
                    action = {
                        "action": "click",
                        "selector": "button:has-text('Next')",
                        "value": None,
                        "key": None,
                        "target_text": None,
                        "text": None,
                        "url": None,
                        "wait_ms": None,
                        "reason": "All birthday fields are filled; continue to next step.",
                    }
                else:
                    auto_actions = choose_form_actions(snapshot)
                    if auto_actions:
                        action = auto_actions.pop(0)
                        auto_action_queue.extend(auto_actions)
                    else:
                        recent_errors = error_history[-3:]
                        action, planner_prompt, planner_raw = choose_action(
                            service,
                            args.goal,
                            step,
                            snapshot,
                            recent_errors,
                        )
                        if args.debug_steps:
                            write_debug_artifact(
                                artifacts_dir=artifacts_dir,
                                step=step,
                                suffix="planner-prompt.txt",
                                payload=planner_prompt,
                            )
                            write_debug_artifact(
                                artifacts_dir=artifacts_dir,
                                step=step,
                                suffix="planner-raw.txt",
                                payload=planner_raw,
                            )
            if args.debug_steps:
                write_debug_artifact(
                    artifacts_dir=artifacts_dir,
                    step=step,
                    suffix="action.json",
                    payload=action,
                )

            signature = action_signature(action)
            repeated_signature_count = repeated_signature_count + 1 if signature == previous_signature else 1
            previous_signature = signature

            if repeated_signature_count >= 3 or stagnant_snapshot_count >= 3:
                action = fallback_action(snapshot)
                previous_signature = action_signature(action)
                repeated_signature_count = 1
                stagnant_snapshot_count = 0
                if args.debug_steps:
                    write_debug_artifact(
                        artifacts_dir=artifacts_dir,
                        step=step,
                        suffix="action.json",
                        payload=action,
                    )

            should_continue = execute_action_step(
                page=page,
                action=action,
                step_number=step,
                artifacts_dir=artifacts_dir,
                action_history=action_history,
                error_history=error_history,
                debug_steps=args.debug_steps,
            )
            if not should_continue:
                print("Agent marked goal as done.")
                break

        final_snapshot = page_snapshot(page)
        final_result = evaluate_run(service, args.goal, final_snapshot, action_history)
        final_result.setdefault("evidence", {"url": final_snapshot["url"], "title": final_snapshot["title"]})
        final_result.setdefault("status", "failed")
        final_result.setdefault("summary", "Run finished without explicit evaluation.")
        final_result.setdefault("email", None)
        final_result.setdefault("password", None)
        final_result["artifacts_dir"] = str(artifacts_dir)
        final_result["steps_executed"] = len(action_history)

        if final_result.get("status") == "success":
            destination_domain = normalize_domain(str(final_snapshot.get("url", "")))
            if destination_domain:
                successful_steps = [
                    entry.get("action")
                    for entry in action_history
                    if isinstance(entry, dict)
                    and isinstance(entry.get("action"), dict)
                    and not entry.get("error")
                ]
                if successful_steps:
                    final_title = str(final_snapshot.get("title", "")).strip()
                    save_recipe(
                        base_dir=recipes_dir,
                        task_key=task_key,
                        domain=destination_domain,
                        steps=successful_steps,
                        source_run={
                            "goal": args.goal,
                            "artifacts_dir": str(artifacts_dir),
                            "steps_executed": len(action_history),
                            "final_url": str(final_snapshot.get("url", "")),
                            "final_title": str(final_snapshot.get("title", "")),
                        },
                        success_signals={
                            "url_contains": [destination_domain],
                            "title_contains": [final_title[:120]] if final_title else [],
                            "body_contains": [],
                        },
                    )

        report_path = artifacts_dir / "run-result.json"
        report_path.write_text(json.dumps(final_result, indent=2), encoding="utf-8")
        print(json.dumps({"final_result": final_result, "report_path": str(report_path)}, ensure_ascii=True))
        browser.close()


if __name__ == "__main__":
    main()

