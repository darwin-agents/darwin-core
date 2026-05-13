from __future__ import annotations

from darwin_web2.observation import observation_fingerprint


def test_observation_fingerprint_stable_for_same_items() -> None:
    items = [
        {"ref": 1, "tag": "button", "role": "", "text": "Next", "value": ""},
        {"ref": 2, "tag": "input", "role": "", "text": "", "value": "x"},
    ]
    a = observation_fingerprint(url="https://example.com/path?q=1", items=items)
    b = observation_fingerprint(url="https://example.com/path?other=2", items=items)
    assert a == b
