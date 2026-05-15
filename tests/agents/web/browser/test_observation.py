from __future__ import annotations

from darwin_core.agents.web.browser.observation import observation_fingerprint, observation_layout_fingerprint


def test_observation_fingerprint_stable_for_same_items() -> None:
    items = [
        {"ref": 1, "tag": "button", "role": "", "text": "Next", "value": ""},
        {"ref": 2, "tag": "input", "role": "", "text": "", "value": "x"},
    ]
    a = observation_fingerprint(url="https://example.com/path?q=1", items=items)
    b = observation_fingerprint(url="https://example.com/path?other=2", items=items)
    assert a == b


def test_layout_fingerprint_ignores_changing_input_values() -> None:
    base = [
        {"ref": 1, "tag": "input", "type": "email", "role": "", "text": "", "value": "aaa"},
        {"ref": 2, "tag": "button", "role": "combobox", "type": "button", "text": "@x.com", "value": "x.com"},
    ]
    changed = [
        {**base[0], "value": "bbb"},
        base[1],
    ]
    url = "https://example.com/signup"
    assert observation_layout_fingerprint(url=url, items=base) == observation_layout_fingerprint(
        url=url, items=changed
    )
    assert observation_fingerprint(url=url, items=base) != observation_fingerprint(
        url=url, items=changed
    )


def test_layout_fingerprint_detects_checkbox_toggle() -> None:
    unchecked = [{"ref": 8, "tag": "input", "type": "checkbox", "checked": "false", "value": "on"}]
    checked = [{"ref": 8, "tag": "input", "type": "checkbox", "checked": "true", "value": "on"}]
    url = "https://mailfence.com/registration/"
    assert observation_layout_fingerprint(url=url, items=unchecked) != observation_layout_fingerprint(
        url=url, items=checked
    )
