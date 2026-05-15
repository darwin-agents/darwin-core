from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from darwin_web.snapshot import PageClosed, resolve_live_page


def _mock_page(*, closed: bool = False, url: str = "https://example.com") -> MagicMock:
    page = MagicMock()
    page.is_closed.return_value = closed
    page.url = url
    return page


def test_resolve_live_page_returns_same_when_open() -> None:
    page = _mock_page(closed=False)
    assert resolve_live_page(page) is page


def test_resolve_live_page_switches_to_open_sibling() -> None:
    closed = _mock_page(closed=True)
    live = _mock_page(closed=False, url="https://mail.yahoo.com/")
    closed.context.pages = [closed, live]
    assert resolve_live_page(closed) is live


def test_resolve_live_page_prefers_non_blank_tab() -> None:
    closed = _mock_page(closed=True)
    blank = _mock_page(closed=False, url="about:blank")
    live = _mock_page(closed=False, url="https://login.yahoo.com/")
    closed.context.pages = [closed, blank, live]
    assert resolve_live_page(closed) is live


def test_resolve_live_page_raises_when_all_closed() -> None:
    closed = _mock_page(closed=True)
    also_closed = _mock_page(closed=True)
    closed.context.pages = [closed, also_closed]
    with pytest.raises(PageClosed, match="already closed"):
        resolve_live_page(closed, allow_spawn=False)


def test_resolve_live_page_prefers_new_tab_after_action() -> None:
    old = _mock_page(closed=False, url="https://login.yahoo.com/")
    new = _mock_page(closed=False, url="https://mail.yahoo.com/")
    old.context.pages = [old, new]
    assert resolve_live_page(old, pages_before={id(old)}) is new


def test_resolve_live_page_spawns_tab_when_context_alive() -> None:
    closed = _mock_page(closed=True)
    fresh = _mock_page(closed=False, url="about:blank")
    closed.context.pages = []
    closed.context.new_page.return_value = fresh
    assert resolve_live_page(closed) is fresh
