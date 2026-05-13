"""Shared JSON body for ``POST /browser/connect`` (Darwin server + HTTP clients)."""

from __future__ import annotations

import os
from typing import Any


def browser_connect_json_body(*, proxy_country_code: str | None = None) -> dict[str, Any]:
    """Build request JSON for :func:`darwin_core.servers.browser_use.app.browser_connect`.

    *proxy_country_code* overrides ``BROWSER_USE_PROXY_COUNTRY_CODE`` when non-empty.
    Values are normalized to lowercase ISO 3166-1 alpha-2 (e.g. ``es`` for Spain).
    """
    raw = proxy_country_code if proxy_country_code is not None else os.getenv("BROWSER_USE_PROXY_COUNTRY_CODE", "")
    code = raw.strip().lower()
    if not code:
        return {}
    return {"proxy_country_code": code}
