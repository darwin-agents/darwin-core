from __future__ import annotations

import pytest

from darwin_core.servers.browser_use.client import browser_connect_json_body


def test_browser_connect_json_body_empty_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BROWSER_USE_PROXY_COUNTRY_CODE", raising=False)
    assert browser_connect_json_body() == {}
    assert browser_connect_json_body(proxy_country_code=None) == {}


def test_browser_connect_json_body_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSER_USE_PROXY_COUNTRY_CODE", "ES")
    assert browser_connect_json_body() == {"proxy_country_code": "es"}


def test_browser_connect_json_body_param_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSER_USE_PROXY_COUNTRY_CODE", "us")
    assert browser_connect_json_body(proxy_country_code="de") == {"proxy_country_code": "de"}
