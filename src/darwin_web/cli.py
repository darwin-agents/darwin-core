from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from darwin_web.browser_connect import request_browser_connect, request_browser_disconnect
from darwin_web.browser_session import BrowserSessionUrls, set_browser_session_urls
from darwin_web.executor import replay_playbook
from darwin_web.llm_client import OpenRouterClient
from darwin_web.navigator import run_goal
from darwin_web.playbook import Playbook


def _build_agent_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="darwin_web: LLM navigation + YAML recipe export.")
    p.add_argument("goal", help="Task description for the browser agent.")
    p.add_argument(
        "--max-steps",
        type=int,
        default=int(os.getenv("DARWIN_WEB_MAX_STEPS", "16")),
        help="Maximum planner turns.",
    )
    p.add_argument(
        "--server-url",
        default=os.getenv("BROWSER_USE_SERVER_URL", "http://localhost:8000"),
        help="darwin-browser-use-server base URL (POST /browser/connect).",
    )
    p.add_argument(
        "--playbook-out",
        type=Path,
        default=Path(os.getenv("DARWIN_WEB_PLAYBOOK_OUT", "artifacts/darwin-web/playbook.yaml")),
        help="Where to write the replay recipe (YAML).",
    )
    p.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path(os.getenv("DARWIN_WEB_ARTIFACTS_DIR", "artifacts/darwin-web")),
        help="Artifacts (*-vision-input.png, *-llm-turn.yaml), playbook copy, etc.",
    )
    p.add_argument(
        "--no-vision",
        action="store_true",
        help="Do not attach page screenshot to the planner LLM (overrides DARWIN_WEB_VISION).",
    )
    p.add_argument(
        "--proxy-country",
        default=None,
        metavar="CODE",
        help="Browser Use proxy country (ISO 3166-1 alpha-2), e.g. es for Spain. "
        "Default: BROWSER_USE_PROXY_COUNTRY_CODE from the environment.",
    )
    return p


def _build_replay_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Replay a darwin_web YAML recipe without an LLM.")
    p.add_argument("playbook", type=Path, help="Path to playbook.yaml (or legacy .json)")
    p.add_argument(
        "--server-url",
        default=os.getenv("BROWSER_USE_SERVER_URL", "http://localhost:8000"),
        help="darwin-browser-use-server base URL.",
    )
    p.add_argument(
        "--step-pause-ms",
        type=int,
        default=int(os.getenv("DARWIN_WEB_REPLAY_PAUSE_MS", "0")),
        help="Optional pause between steps (milliseconds).",
    )
    p.add_argument(
        "--proxy-country",
        default=None,
        metavar="CODE",
        help="Browser Use proxy country (ISO 3166-1 alpha-2), e.g. es for Spain. "
        "Default: BROWSER_USE_PROXY_COUNTRY_CODE from the environment.",
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

            result = run_goal(
                page=page,
                goal=args.goal,
                llm=llm,
                max_steps=args.max_steps,
                artifacts_dir=args.artifacts_dir,
                playbook_out=args.playbook_out,
                vision=False if args.no_vision else None,
            )
            result.playbook.write(args.playbook_out)
            secondary = args.artifacts_dir / "playbook.yaml"
            if secondary.resolve() != args.playbook_out.resolve():
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
        "playbook_path": str(args.playbook_out),
        "planner_turns": result.planner_turns,
        "errors": result.errors,
        "final_summary": result.playbook.final_summary,
    }
    print(json.dumps(out, ensure_ascii=True, indent=2))
    return 0 if result.completed else 2


def main_replay(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _build_replay_parser().parse_args(argv)
    pb = Playbook.read(args.playbook)
    cdp = request_cdp_url(args.server_url, proxy_country_code=args.proxy_country)

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()
        replay_playbook(page, pb.steps, pause_ms=args.step_pause_ms)
        browser.close()

    print(json.dumps({"ok": True, "steps": len(pb.steps)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main_agent())
