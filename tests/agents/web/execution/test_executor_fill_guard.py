from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from darwin_core.agents.web.execution.executor import (
    _post_click_settle_ms,
    _redundant_text_fill_should_skip,
    run_planner_action,
)


def test_post_click_settle_ms_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DARWIN_WEB_POST_CLICK_MS", raising=False)
    assert _post_click_settle_ms() == 1000
    monkeypatch.setenv("DARWIN_WEB_POST_CLICK_MS", "0")
    assert _post_click_settle_ms() == 0
    monkeypatch.setenv("DARWIN_WEB_POST_CLICK_MS", "999999")
    assert _post_click_settle_ms() == 10_000


def test_redundant_fill_skip_when_equal() -> None:
    assert _redundant_text_fill_should_skip(current="1", desired="1") is True
    assert _redundant_text_fill_should_skip(current=" 1 ", desired="1") is True
    assert _redundant_text_fill_should_skip(current="x", desired="y") is False
    assert _redundant_text_fill_should_skip(current=None, desired="1") is False


def test_fill_missing_ref_returns_error() -> None:
    page = MagicMock()
    cont, step, err, _meta = run_planner_action(
        page,
        {"op": "fill", "value": "01", "describe": "enter day"},
    )
    assert cont is True
    assert step is None
    assert err
    assert "ref" in err.lower()


def test_click_missing_ref_returns_error() -> None:
    page = MagicMock()
    cont, step, err, _meta = run_planner_action(page, {"op": "click", "describe": "go"})
    assert cont is True
    assert step is None
    assert err
    assert "ref" in err.lower()


def test_fill_combobox_ref_returns_guidance() -> None:
    page = MagicMock()
    loc = MagicMock()
    page.locator.return_value = loc
    loc_first = MagicMock()
    loc.first = loc_first
    handle = MagicMock()
    loc_first.element_handle.return_value = handle

    handle.evaluate.side_effect = [
        "div.widget",
        {"tag": "div", "role": "combobox", "id": "m"},
        False,  # not HTMLSelectElement
        False,  # not fillable (custom combobox)
    ]

    cont, step, err, _meta = run_planner_action(
        page,
        {"op": "fill", "ref": 2, "value": "01", "describe": "day"},
    )
    assert cont is True
    assert step is None
    assert err
    assert "combobox" in err.lower()
    handle.dispose.assert_called_once()
