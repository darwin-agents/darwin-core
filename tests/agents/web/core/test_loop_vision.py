from __future__ import annotations

from darwin_core.agents.web.core.loop import _is_blank_start_page, _should_attach_vision
from darwin_core.agents.web.browser.observation import Observation


def _obs(**kwargs: object) -> Observation:
    items = kwargs.pop("items", [])
    defaults: dict[str, object] = {
        "url": "about:blank",
        "title": "",
        "items": items,
        "alert_digest": "",
        "aria_snapshot": "",
        "form_html": "",
        "layout_fingerprint": "x",
        "fingerprint": "y",
        "element_count": len(items) if isinstance(items, list) else 0,
    }
    defaults.update(kwargs)
    return Observation(**defaults)  # type: ignore[arg-type]


def test_blank_start_page() -> None:
    assert _is_blank_start_page(_obs())
    assert not _is_blank_start_page(
        _obs(url="https://mailfence.com/", title="Mailfence", items=[{"ref": 1}])
    )


def test_skip_vision_on_blank() -> None:
    assert not _should_attach_vision(_obs(), use_vision=True)
    assert _should_attach_vision(
        _obs(url="https://mailfence.com/", items=[{"ref": 1}]),
        use_vision=True,
    )
