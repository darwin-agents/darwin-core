from __future__ import annotations

from darwin_core.agents.web.integrations.llm_client import _extract_json_object


def test_extract_json_ignores_trailing_prose() -> None:
    raw = _extract_json_object(
        '{"thought":"t","action":{"op":"wait_ms","ms":100,"describe":"x"}}  Thanks!'
    )
    assert raw["action"]["op"] == "wait_ms"


def test_extract_json_skips_preamble() -> None:
    raw = _extract_json_object('Sure. Here you go:\n{"thought":"t","action":{"op":"done","summary":"ok"}}')
    assert raw["action"]["op"] == "done"


def test_extract_json_root_array_wrapped_planner() -> None:
    raw = _extract_json_object('[{"thought":"t","action":{"op":"goto","url":"https://x","describe":"open"}}]')
    assert raw["thought"] == "t"
    assert raw["action"]["op"] == "goto"


def test_extract_json_root_array_action_only() -> None:
    raw = _extract_json_object('[{"op":"press","key":"Enter","describe":"submit"}]')
    assert raw["action"]["op"] == "press"
