from __future__ import annotations

import httpx


def request_cdp_url(server_url: str, *, timeout: float = 20.0) -> str:
    """Call the Darwin ``darwin-browser-use-server`` ``POST /browser/connect`` endpoint."""
    response = httpx.post(
        f"{server_url.rstrip('/')}/browser/connect",
        json={},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    cdp_ws_url = data.get("cdp_ws_url")
    if not isinstance(cdp_ws_url, str) or not cdp_ws_url:
        raise RuntimeError("Invalid /browser/connect response: missing cdp_ws_url.")
    return cdp_ws_url
