from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from playwright._impl._errors import Error as PlaywrightError

from darwin_core.agents.web.browser.snapshot import PageNavigating, _is_transient_navigation_error, page_snapshot


def test_is_transient_navigation_error() -> None:
    assert _is_transient_navigation_error(
        PlaywrightError("Page.evaluate: Execution context was destroyed, most likely because of a navigation")
    )


def test_page_snapshot_retries_after_navigation_race(monkeypatch: pytest.MonkeyPatch) -> None:
    page = MagicMock()
    page.is_closed.return_value = False
    page.url = "https://example.com/after"
    nav_err = PlaywrightError("Execution context was destroyed, most likely because of a navigation")
    # clear_refs + snapshot each call evaluate; first snapshot races navigation, second succeeds.
    page.evaluate.side_effect = [None, nav_err, None, [{"ref": 1, "tag": "button", "text": "OK"}]]
    monkeypatch.setattr("darwin_core.agents.web.browser.snapshot.resolve_live_page", lambda p, **kw: p)
    monkeypatch.setattr("darwin_core.agents.web.browser.snapshot._snapshot_nav_retry_attempts", lambda: 3)
    items, url = page_snapshot(page, max_items=8)
    assert len(items) == 1
    assert url == "https://example.com/after"
    assert page.evaluate.call_count == 4


def test_clear_refs_raises_page_navigating() -> None:
    from darwin_core.agents.web.browser.snapshot import clear_refs

    page = MagicMock()
    page.is_closed.return_value = False
    page.evaluate.side_effect = PlaywrightError("Execution context was destroyed")
    with pytest.raises(PageNavigating):
        clear_refs(page)
