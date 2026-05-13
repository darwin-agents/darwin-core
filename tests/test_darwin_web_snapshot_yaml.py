from __future__ import annotations

import yaml

from darwin_web.snapshot import _ALERT_DIGEST_JS, snapshot_items_yaml


def test_alert_digest_js_does_not_query_polite_live_regions() -> None:
    assert '[aria-live="polite"]' not in _ALERT_DIGEST_JS
    assert 'aria-live="assertive"' in _ALERT_DIGEST_JS


def test_snapshot_items_yaml_roundtrips_list() -> None:
    items = [{"ref": 1, "tag": "button", "text": "Next", "value": ""}]
    dumped = snapshot_items_yaml(items)
    loaded = yaml.safe_load(dumped)
    assert isinstance(loaded, list)
    assert loaded[0]["ref"] == 1
    assert loaded[0]["tag"] == "button"
