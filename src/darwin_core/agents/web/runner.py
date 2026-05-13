from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from darwin_core.servers.browser_use.client import browser_connect_json_body
from darwin_core.services.llm.openrouter import OpenRouterService

from .session import run_web_navigation
from .web_owner_profile import WebOwnerProfile, load_web_owner_profile


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
    parser.add_argument(
        "--owner-profile",
        default=os.getenv("OPENROUTER_WEB_OWNER_PROFILE"),
        metavar="PATH",
        help="JSON file with the human owner's identity for form auto-fill (or set OPENROUTER_WEB_OWNER_PROFILE).",
    )
    parser.add_argument(
        "--proxy-country",
        default=None,
        metavar="CODE",
        help="Browser Use proxy country (ISO 3166-1 alpha-2), e.g. es for Spain. "
        "Default: BROWSER_USE_PROXY_COUNTRY_CODE from the environment.",
    )
    return parser


def request_cdp_url(server_url: str, *, proxy_country_code: str | None = None) -> str:
    body = browser_connect_json_body(proxy_country_code=proxy_country_code)
    response = httpx.post(
        f"{server_url.rstrip('/')}/browser/connect",
        json=body,
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
    if not args.owner_profile:
        parser.error(
            "Missing owner profile: pass --owner-profile PATH or set OPENROUTER_WEB_OWNER_PROFILE "
            "to a JSON file with email, password, first_name, last_name, phone, birth_day, "
            "birth_month, birth_year, gender (optional key: generic_text)."
        )
    owner_profile: WebOwnerProfile = load_web_owner_profile(args.owner_profile)

    cdp_ws_url = request_cdp_url(args.server_url, proxy_country_code=args.proxy_country)
    service = OpenRouterService()
    artifacts_dir = Path(args.artifacts_dir)
    recipes_dir = Path(args.recipes_dir)
    recipes_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_ws_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()

        result = run_web_navigation(
            page=page,
            goal=args.goal,
            owner_profile=owner_profile,
            service=service,
            artifacts_dir=artifacts_dir,
            recipes_dir=recipes_dir,
            max_steps=args.max_steps,
            debug_steps=args.debug_steps,
        )

        report_path = artifacts_dir / "run-result.json"
        report_path.write_text(json.dumps(result.final_result, indent=2), encoding="utf-8")
        print(json.dumps({"final_result": result.final_result, "report_path": str(report_path)}, ensure_ascii=True))
        browser.close()


if __name__ == "__main__":
    main()
