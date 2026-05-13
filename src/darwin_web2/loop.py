"""Main observe → plan → act → verify loop for darwin_web2."""

from __future__ import annotations

import copy
import json
import os
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from playwright.sync_api import Page

from darwin_web.genhash import reset_pw_cache
from darwin_web.llm_client import LLMTurnTranscript, OpenRouterClient
from darwin_web.playbook import PlaybookStep
from darwin_web.snapshot import PageClosed, safe_page_url
from darwin_web.step_screenshots import write_vision_input_png
from darwin_web.telegram_hil import consume_last_owner_telegram_reply

from darwin_web2.accounts import append_account_record, default_accounts_path
from darwin_web2.coerce import coerce_planner_raw
from darwin_web2.executor import run_planner_action
from darwin_web2.observation import Observation, gather_observation, nav_breadcrumb
from darwin_web2.playbook import AnnotatedStep, PlaybookV2, goal_fingerprint
from darwin_web2.policy import SYSTEM_PROMPT
from darwin_web2.reflect import reflect_enabled, reflect_repair_action
from darwin_web2.verify import VerifyOutcome, verify_after_step


def _vision_default(vision: bool | None) -> bool:
    if vision is not None:
        return vision
    v = os.getenv("DARWIN_WEB2_VISION", os.getenv("DARWIN_WEB_VISION", "1")).strip().lower()
    return v not in ("0", "false", "no", "off")


def _done_summary_partial(summary: str) -> bool:
    s = (summary or "").lower()
    return any(
        phrase in s
        for phrase in (
            " up to ",
            " up to the",
            " partial ",
            "partially",
            " so far ",
            " not yet complete",
            " not complete",
            "next step",
            " before finishing",
            " halfway",
            "not finished",
        )
    )


def _llm_turn_path(artifacts_dir: Path, turn: int) -> Path:
    return artifacts_dir / f"{turn:03d}-llm-turn-v2.yaml"


def _write_turn_artifact(
    path: Path,
    *,
    turn: int,
    page_url: str,
    model: str,
    user_text: str,
    planner: dict[str, Any] | None,
    transcript: LLMTurnTranscript | None,
    execution: dict[str, Any] | None,
    error: str | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any] = {
        "kind": "darwin_web2_llm_turn",
        "turn": turn,
        "page_url": page_url,
        "request": {"model": model},
        "prompt": {"user_text": user_text},
    }
    if planner is not None:
        doc["planner"] = planner
    if transcript is not None:
        doc["response"] = {
            "assistant_text": transcript.assistant_raw,
            "assistant_parsed": transcript.assistant_parsed,
        }
    if execution is not None:
        doc["execution"] = execution
    if error is not None:
        doc["error"] = error
    path.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False, width=120),
        encoding="utf-8",
    )


@dataclass
class NavigationResultV2:
    playbook: PlaybookV2
    completed: bool
    errors: list[str]
    planner_turns: int
    final_summary: str | None = None


def _execute_once(
    page: Page,
    action: dict[str, Any],
    obs_before: Observation,
    fingerprint_history: deque[str],
    *,
    vision_png_path: Path | None,
    default_timeout_ms: float,
) -> tuple[bool, PlaybookStep | None, str | None, Observation, VerifyOutcome]:
    """Returns (continue_loop, playbook_step_or_none, executor_err, obs_after, verify_outcome)."""
    cont, pb_step, err = run_planner_action(
        page,
        action,
        default_timeout_ms=default_timeout_ms,
        vision_png_path=vision_png_path,
    )
    try:
        obs_after = gather_observation(page)
    except PageClosed:
        raise
    except Exception:  # noqa: BLE001
        obs_after = obs_before
    vo = verify_after_step(
        obs_before=obs_before,
        obs_after=obs_after,
        executor_error=err,
        fingerprint_history=fingerprint_history,
    )
    return cont, pb_step, err, obs_after, vo


def run_goal(
    *,
    page: Page,
    goal: str,
    llm: OpenRouterClient,
    max_steps: int,
    artifacts_dir: Path | None = None,
    playbook_out: Path | None = None,
    vision: bool | None = None,
    accounts_path: Path | None = None,
    default_timeout_ms: float = 12_000,
) -> NavigationResultV2:
    errors: list[str] = []
    recorded: list[AnnotatedStep] = []
    completed = False
    final_summary: str | None = None
    last_turn = 0
    use_vision = _vision_default(vision)
    fingerprint_history: deque[str] = deque(maxlen=4)
    last_nav: str | None = None
    verify_feedback = ""
    step_seq = 0
    acc_path = accounts_path if accounts_path is not None else default_accounts_path()

    # Load owner profile for form-filling context.
    owner_profile_block = ""
    owner_config_path = Path(os.getenv(
        "DARWIN_WEB2_OWNER_CONFIG",
        str(Path(__file__).resolve().parents[2] / "config" / "owner.json"),
    ))
    if owner_config_path.is_file():
        try:
            owner_data = json.loads(owner_config_path.read_text(encoding="utf-8"))
            if isinstance(owner_data, dict) and owner_data:
                lines = [f"  {k}: {v}" for k, v in owner_data.items() if isinstance(v, str) and v.strip()]
                if lines:
                    owner_profile_block = "\nOWNER_PROFILE (use these values for form fields):\n" + "\n".join(lines) + "\n"
        except Exception:  # noqa: BLE001
            pass

    if artifacts_dir is not None:
        artifacts_dir.mkdir(parents=True, exist_ok=True)

    for turn in range(1, max_steps + 1):
        last_turn = turn
        try:
            obs = gather_observation(page)
        except PageClosed as exc:
            errors.append(str(exc))
            break

        nav = nav_breadcrumb(obs.url)
        if last_nav is not None and nav != last_nav:
            errors.clear()
            fingerprint_history.clear()
            reset_pw_cache()
        last_nav = nav

        owner_reply = consume_last_owner_telegram_reply()
        owner_block = ""
        if owner_reply:
            owner_block = (
                "\nOwner message (Telegram; treat as authoritative guidance for this turn):\n"
                f"{owner_reply}\n"
            )

        user_block = (
            f"USER_GOAL:\n{goal}\n"
            + owner_profile_block
            + owner_block
            + verify_feedback
            + "\n\n"
            + obs.to_prompt_block()
            + '\n\nReturn JSON with "thought" and "action".'
        )

        vision_path: Path | None = None
        if artifacts_dir is not None and use_vision:
            p = write_vision_input_png(page, artifacts_dir, turn)
            vision_path = p if p is not None else None

        transcript: LLMTurnTranscript | None = None
        raw: dict[str, Any] | None = None
        try:
            transcript = llm.chat_planner_turn(
                user_block,
                system_prompt=SYSTEM_PROMPT,
                vision_png_path=vision_path,
            )
            raw = copy.deepcopy(transcript.assistant_parsed)
            coerce_planner_raw(raw)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"llm:{exc}")
            if artifacts_dir is not None:
                _write_turn_artifact(
                    _llm_turn_path(artifacts_dir, turn),
                    turn=turn,
                    page_url=obs.url,
                    model=llm.model,
                    user_text=user_block,
                    planner=None,
                    transcript=None,
                    execution=None,
                    error=str(exc),
                )
            continue

        action = raw.get("action")
        if not isinstance(action, dict):
            errors.append(f"turn {turn}: missing action dict")
            if artifacts_dir is not None:
                _write_turn_artifact(
                    _llm_turn_path(artifacts_dir, turn),
                    turn=turn,
                    page_url=obs.url,
                    model=llm.model,
                    user_text=user_block,
                    planner={"thought": raw.get("thought"), "action": None},
                    transcript=transcript,
                    execution=None,
                    error="missing action dict",
                )
            continue

        if action.get("op") == "done":
            summary = action.get("summary")
            if isinstance(summary, str) and _done_summary_partial(summary):
                msg = f"turn {turn}: ignored invalid done (partial milestone): {summary.strip()[:120]!r}"
                errors.append(msg)
                if artifacts_dir is not None:
                    _write_turn_artifact(
                        _llm_turn_path(artifacts_dir, turn),
                        turn=turn,
                        page_url=obs.url,
                        model=llm.model,
                        user_text=user_block,
                        planner={"thought": raw.get("thought"), "action": action},
                        transcript=transcript,
                        execution={"invalid_done": True},
                        error=None,
                    )
                continue

            final_summary = summary.strip() if isinstance(summary, str) and summary.strip() else "done"
            gfp = goal_fingerprint(goal, obs.url)
            pb = PlaybookV2(
                goal=goal,
                steps=recorded,
                goal_fingerprint=gfp,
                final_summary=final_summary,
            )
            if playbook_out is not None:
                pb.write(playbook_out)
            creds = action.get("credentials")
            if isinstance(creds, dict):
                creds_out = {k: str(v) for k, v in creds.items() if isinstance(k, str) and isinstance(v, str)}
            else:
                creds_out = {}
            append_account_record(
                acc_path,
                {
                    "completed_at": pb.created_at,
                    "goal": goal,
                    "final_summary": final_summary,
                    "playbook_path": str(playbook_out) if playbook_out else "",
                    "goal_fingerprint": gfp,
                    **({"credentials": creds_out} if creds_out else {}),
                },
            )
            completed = True
            if artifacts_dir is not None:
                _write_turn_artifact(
                    _llm_turn_path(artifacts_dir, turn),
                    turn=turn,
                    page_url=obs.url,
                    model=llm.model,
                    user_text=user_block,
                    planner={"thought": raw.get("thought"), "action": action},
                    transcript=transcript,
                    execution={"completed": True},
                    error=None,
                )
            return NavigationResultV2(
                playbook=pb,
                completed=True,
                errors=errors,
                planner_turns=last_turn,
                final_summary=final_summary,
            )

        obs_before = obs
        exec_docs: list[dict[str, Any]] = []

        def run_action(act: dict[str, Any], tag: str, *, allow_reflect: bool = True) -> None:
            nonlocal obs_before, recorded, step_seq, errors, exec_docs, verify_feedback
            cont, pb_step, err, obs_after, vo = _execute_once(
                page,
                act,
                obs_before,
                fingerprint_history,
                vision_png_path=vision_path,
                default_timeout_ms=default_timeout_ms,
            )
            doc: dict[str, Any] = {
                "tag": tag,
                "continue_loop": cont,
                "executor_message": err,
                "verify_messages": list(vo.messages),
                "stagnation": vo.stagnation,
            }
            if pb_step is not None:
                step_seq += 1
                recorded.append(
                    AnnotatedStep(pb_step, step_id=f"s{step_seq}", semantic=None),
                )
                doc["recorded"] = pb_step.to_recipe_dict()
            exec_docs.append(doc)
            if err:
                errors.append(f"turn {turn}: {err}")
            obs_before = obs_after
            if vo.messages:
                verify_feedback = "\nVerify feedback:\n" + "\n".join(f"- {m}" for m in vo.messages) + "\n"
            else:
                verify_feedback = ""

            if (
                allow_reflect
                and reflect_enabled()
                and (err or not vo.ok)
            ):
                rep = reflect_repair_action(
                    llm=llm,
                    goal=goal,
                    observation_text=obs_after.to_prompt_block(),
                    last_action=act,
                    verify_messages=vo.messages,
                )
                if rep and isinstance(rep.get("action"), dict):
                    act2 = rep["action"]
                    if json.dumps(act2, sort_keys=True) != json.dumps(act, sort_keys=True):
                        run_action(act2, "reflect", allow_reflect=False)

        run_action(action, "planner")

        if artifacts_dir is not None:
            _write_turn_artifact(
                _llm_turn_path(artifacts_dir, turn),
                turn=turn,
                page_url=obs.url,
                model=llm.model,
                user_text=user_block,
                planner={"thought": raw.get("thought"), "action": action},
                transcript=transcript,
                execution={"runs": exec_docs},
                error=None,
            )

    gfp = goal_fingerprint(goal, safe_page_url(page))
    pb = PlaybookV2(goal=goal, steps=recorded, goal_fingerprint=gfp, final_summary=final_summary)
    if playbook_out is not None and recorded:
        pb.write(playbook_out)
    return NavigationResultV2(
        playbook=pb,
        completed=completed,
        errors=errors,
        planner_turns=last_turn,
        final_summary=final_summary,
    )
