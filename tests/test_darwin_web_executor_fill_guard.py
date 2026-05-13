from __future__ import annotations

from darwin_web.executor import _redundant_text_fill_should_skip


def test_redundant_fill_skip_when_equal() -> None:
    assert _redundant_text_fill_should_skip(current="1", desired="1") is True
    assert _redundant_text_fill_should_skip(current=" 1 ", desired="1") is True
    assert _redundant_text_fill_should_skip(current="x", desired="y") is False
    assert _redundant_text_fill_should_skip(current=None, desired="1") is False
