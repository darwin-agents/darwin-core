"""Active browser session URLs for the current automation run (Telegram HIL, owner attach)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserSessionUrls:
    browser_id: str
    cdp_ws_url: str
    live_url: str
    server_url: str = ""


_session: BrowserSessionUrls | None = None


def set_browser_session_urls(urls: BrowserSessionUrls | None) -> None:
    """Store connect endpoints for this agent run."""
    global _session  # noqa: PLW0603
    _session = urls


def set_browser_cdp_ws_url(url: str | None) -> None:
    """Legacy: CDP URL only (no browser_id; live URL derived)."""
    if url is None or not str(url).strip():
        set_browser_session_urls(None)
        return
    from darwin_core.agents.web.browser.browser_connect import live_url_from_cdp_ws

    wss = str(url).strip()
    set_browser_session_urls(
        BrowserSessionUrls(browser_id="", cdp_ws_url=wss, live_url=live_url_from_cdp_ws(wss))
    )


def get_browser_session_urls() -> BrowserSessionUrls | None:
    return _session


def get_browser_cdp_ws_url() -> str | None:
    s = _session
    return s.cdp_ws_url if s is not None else None


def get_browser_live_url() -> str | None:
    s = _session
    return s.live_url if s is not None else None


def get_browser_id() -> str | None:
    s = _session
    if s is None or not s.browser_id:
        return None
    return s.browser_id


def get_browser_server_url() -> str | None:
    s = _session
    if s is not None and s.server_url.strip():
        return s.server_url.strip()
    env = os.getenv("BROWSER_USE_SERVER_URL", "").strip()
    return env or None
