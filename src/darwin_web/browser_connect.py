from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import httpx

from darwin_core.servers.browser_use.client import browser_connect_json_body


@dataclass(frozen=True)
class BrowserConnectInfo:
    """Endpoints for one Browser Use Cloud session."""

    browser_id: str
    cdp_ws_url: str
    live_url: str


def live_url_from_cdp_ws(cdp_ws_url: str) -> str:
    """Fallback when server did not return liveUrl (legacy generic connect only)."""
    wss = cdp_ws_url.strip()
    return f"https://live.browser-use.com?wss={quote(wss, safe='')}"


def request_browser_connect(
    server_url: str,
    *,
    proxy_country_code: str | None = None,
    timeout: float = 60.0,
) -> BrowserConnectInfo:
    """Call ``POST /browser/connect`` on the local Browser Use bridge server."""
    body = browser_connect_json_body(proxy_country_code=proxy_country_code)
    response = httpx.post(
        f"{server_url.rstrip('/')}/browser/connect",
        json=body,
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    browser_id = data.get("browser_id")
    cdp_ws_url = data.get("cdp_ws_url")
    if not isinstance(browser_id, str) or not browser_id:
        raise RuntimeError("Invalid /browser/connect response: missing browser_id.")
    if not isinstance(cdp_ws_url, str) or not cdp_ws_url:
        raise RuntimeError("Invalid /browser/connect response: missing cdp_ws_url.")
    live = data.get("live_url")
    if not isinstance(live, str) or not live.strip():
        live = live_url_from_cdp_ws(cdp_ws_url)
    return BrowserConnectInfo(
        browser_id=browser_id,
        cdp_ws_url=cdp_ws_url,
        live_url=live.strip(),
    )


def request_browser_disconnect(
    server_url: str,
    browser_id: str,
    *,
    timeout: float = 30.0,
) -> None:
    """Call ``POST /browser/disconnect`` to stop the cloud browser."""
    response = httpx.post(
        f"{server_url.rstrip('/')}/browser/disconnect",
        json={"browser_id": browser_id},
        timeout=timeout,
    )
    response.raise_for_status()


def request_cdp_url(
    server_url: str,
    *,
    proxy_country_code: str | None = None,
    timeout: float = 60.0,
) -> str:
    """Backward-compatible: CDP URL only."""
    return request_browser_connect(
        server_url, proxy_country_code=proxy_country_code, timeout=timeout
    ).cdp_ws_url
