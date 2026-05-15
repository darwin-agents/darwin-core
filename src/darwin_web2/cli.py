from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from darwin_web.browser_connect import request_browser_connect, request_browser_disconnect
from darwin_web.browser_session import BrowserSessionUrls, set_browser_session_urls
from darwin_web.llm_client import OpenRouterClient
from darwin_web.snapshot import safe_page_url

from darwin_web2.executor import replay_playbook
from darwin_web2.loop import run_goal
from darwin_web2.playbook import PlaybookV2
from darwin_web2.repair import replay_annotated_steps_until_failure, write_repair_marker


def _build_agent_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="darwin_web2: observe → verify web agent + playbook v2.")
    p.add_argument("goal", help="Task description for the browser agent.")
    p.add_argument(
        "--max-steps",
        type=int,
        default=int(os.getenv("DARWIN_WEB2_MAX_STEPS", os.getenv("DARWIN_WEB_MAX_STEPS", "32"))),
        help="Maximum planner turns.",
    )
    p.add_argument(
        "--server-url",
        default=os.getenv("BROWSER_USE_SERVER_URL", "http://localhost:8000"),
        help="browser-use server base URL (POST /browser/connect).",
    )
    p.add_argument(
        "--playbook-out",
        type=Path,
        default=Path(os.getenv("DARWIN_WEB2_PLAYBOOK_OUT", "artifacts/darwin-web2/playbook.yaml")),
        help="Where to write the v2 YAML playbook.",
    )
    p.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path(os.getenv("DARWIN_WEB2_ARTIFACTS_DIR", "artifacts/darwin-web2")),
        help="Turn artifacts (*-llm-turn-v2.yaml, *-vision-input.png).",
    )
    p.add_argument(
        "--accounts-path",
        type=Path,
        default=None,
        help="Override DARWIN_WEB2_ACCOUNTS_PATH for JSONL account records.",
    )
    p.add_argument(
        "--emails-config",
        type=Path,
        default=None,
        help="Ranked email providers JSON (easiest→hardest). Default: config/emails.json.",
    )
    p.add_argument(
        "--no-vision",
        action="store_true",
        help="Do not attach screenshot to the planner LLM.",
    )
    p.add_argument(
        "--proxy-country",
        default=None,
        metavar="CODE",
        help="Browser Use proxy country (ISO 3166-1 alpha-2).",
    )
    return p


def _build_replay_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Replay a darwin_web2 v2 playbook (YAML).")
    p.add_argument("playbook", type=Path, help="Path to playbook.yaml")
    p.add_argument(
        "--server-url",
        default=os.getenv("BROWSER_USE_SERVER_URL", "http://localhost:8000"),
        help="browser-use server base URL.",
    )
    p.add_argument(
        "--step-pause-ms",
        type=int,
        default=int(os.getenv("DARWIN_WEB2_REPLAY_PAUSE_MS", "0")),
        help="Pause between steps (ms).",
    )
    p.add_argument(
        "--proxy-country",
        default=None,
        metavar="CODE",
        help="Browser Use proxy country (ISO 3166-1 alpha-2).",
    )
    p.add_argument(
        "--no-repair-marker",
        action="store_true",
        help="Do not write playbook.repair.yaml on failure.",
    )
    p.add_argument(
        "--use-legacy-replay",
        action="store_true",
        help="Use bulk replay_playbook (fail-fast on first error without step index).",
    )
    return p


def main_agent(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _build_agent_parser().parse_args(argv)
    llm = OpenRouterClient()
    connect = request_browser_connect(args.server_url, proxy_country_code=args.proxy_country)
    set_browser_session_urls(
        BrowserSessionUrls(
            browser_id=connect.browser_id,
            cdp_ws_url=connect.cdp_ws_url,
            live_url=connect.live_url,
        )
    )

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(connect.cdp_ws_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()

            def _focus_new_tab(new_page) -> None:  # noqa: ANN001 — Playwright callback
                nonlocal page
                try:
                    new_page.bring_to_front()
                except Exception:  # noqa: BLE001
                    pass
                page = new_page

            context.on("page", _focus_new_tab)

            result = run_goal(
                page=page,
                goal=args.goal,
                llm=llm,
                max_steps=args.max_steps,
                artifacts_dir=args.artifacts_dir,
                playbook_out=args.playbook_out,
                vision=False if args.no_vision else None,
                accounts_path=args.accounts_path,
                emails_config_path=args.emails_config,
            )
            secondary = args.artifacts_dir / "playbook.yaml"
            if (
                args.playbook_out is not None
                and result.playbook.steps
                and secondary.resolve() != args.playbook_out.resolve()
            ):
                result.playbook.write(secondary)
            browser.close()
    finally:
        set_browser_session_urls(None)
        try:
            request_browser_disconnect(args.server_url, connect.browser_id)
        except Exception:  # noqa: BLE001
            pass

    out = {
        "completed": result.completed,
        "browser_id": connect.browser_id,
        "browser_cdp_ws_url": connect.cdp_ws_url,
        "browser_live_url": connect.live_url,
        "playbook_path": str(args.playbook_out) if args.playbook_out else "",
        "planner_turns": result.planner_turns,
        "errors": result.errors,
        "final_summary": result.final_summary,
        "goal_fingerprint": result.playbook.goal_fingerprint,
    }
    print(json.dumps(out, ensure_ascii=True, indent=2))
    return 0 if result.completed else 2


def main_replay(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _build_replay_parser().parse_args(argv)
    pb = PlaybookV2.read(args.playbook)
    cdp = request_cdp_url(args.server_url, proxy_country_code=args.proxy_country)

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()
        if args.use_legacy_replay:
            try:
                replay_playbook(page, pb.legacy_steps(), pause_ms=args.step_pause_ms)
                ok, fail_i, err = True, None, None
            except Exception as exc:  # noqa: BLE001
                ok, fail_i, err = False, None, str(exc)
        else:
            ok, fail_i, err = replay_annotated_steps_until_failure(
                page,
                pb.steps,
                default_timeout_ms=float(os.getenv("DARWIN_WEB2_TIMEOUT_MS", "12000")),
            )
        page_url = safe_page_url(page)
        browser.close()

    if not ok and not args.no_repair_marker and fail_i is not None:
        write_repair_marker(
            args.playbook,
            failed_index=fail_i,
            error=err or "replay failed",
            page_url=page_url,
        )

    print(
        json.dumps(
            {"ok": ok, "steps": len(pb.steps), "failed_step": fail_i, "error": err},
            ensure_ascii=True,
        )
    )
    return 0 if ok else 3


def main() -> int:
    """Dispatch: ``darwin-web2-agent`` entrypoint defaults to agent."""
    return main_agent()


if __name__ == "__main__":
    raise SystemExit(main())
