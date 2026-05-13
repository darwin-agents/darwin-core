from __future__ import annotations

import httpx

from darwin_core.servers.browser_use.client import browser_connect_json_body


def request_cdp_url(
    server_url: str,
    *,
    proxy_country_code: str | None = None,
    timeout: float = 20.0,
) -> str:
    """Call the Darwin ``darwin-browser-use-server`` ``POST /browser/connect`` endpoint.

    *proxy_country_code* overrides ``BROWSER_USE_PROXY_COUNTRY_CODE`` for this request when set.
    """
    body = browser_connect_json_body(proxy_country_code=proxy_country_code)
    response = httpx.post(
        f"{server_url.rstrip('/')}/browser/connect",
        json=body,
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    cdp_ws_url = data.get("cdp_ws_url")
    if not isinstance(cdp_ws_url, str) or not cdp_ws_url:
        raise RuntimeError("Invalid /browser/connect response: missing cdp_ws_url.")
    return cdp_ws_url
