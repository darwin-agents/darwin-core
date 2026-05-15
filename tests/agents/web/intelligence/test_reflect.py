from __future__ import annotations

from darwin_core.agents.web.intelligence.reflect import reflect_repair_action


class _StubLLM:
    def __init__(self, payload: dict | None = None, *, raise_json: bool = False) -> None:
        self.payload = payload or {}
        self.raise_json = raise_json

    def chat_json(self, user_prompt: str, *, system_prompt: str) -> dict:
        if self.raise_json:
            raise ValueError("No JSON object found in model output.")
        return dict(self.payload)

    def chat_planner_turn(self, user_prompt: str, *, system_prompt: str, vision_png_path=None) -> object:
        if self.raise_json:
            raise ValueError("No JSON object found in model output.")
        from types import SimpleNamespace

        return SimpleNamespace(assistant_parsed=dict(self.payload))


def test_reflect_returns_none_without_messages() -> None:
    llm = _StubLLM({"thought": "x", "action": {"op": "wait_ms", "ms": 0, "describe": "d"}})
    assert (
        reflect_repair_action(
            llm=llm,
            goal="g",
            observation_text="o",
            last_action={"op": "click", "ref": 1, "describe": "x"},
            verify_messages=(),
        )
        is None
    )


def test_reflect_returns_coerced_action() -> None:
    llm = _StubLLM(
        {
            "thought": "fix",
            "action": {"op": "wait_ms", "ms": 0, "describe": "settle"},
        }
    )
    raw = reflect_repair_action(
        llm=llm,
        goal="g",
        observation_text="obs",
        last_action={"op": "click", "ref": 1, "describe": "x"},
        verify_messages=("stagnation: stuck",),
    )
    assert raw is not None
    assert raw["action"]["op"] == "wait_ms"


def test_reflect_avoids_repeated_click_on_same_ref() -> None:
    llm = _StubLLM(
        {
            "thought": "retry",
            "action": {"op": "click", "ref": 4, "describe": "again"},
        }
    )
    raw = reflect_repair_action(
        llm=llm,
        goal="g",
        observation_text="obs",
        last_action={"op": "click", "ref": 4, "describe": "x"},
        verify_messages=("stagnation: repeated click on ref 4 three times without progress",),
    )
    assert raw is not None
    assert raw["action"]["op"] == "wait_ms"
    assert "ref" not in raw["action"]


def test_reflect_returns_none_when_llm_output_not_json() -> None:
    llm = _StubLLM(raise_json=True)
    assert (
        reflect_repair_action(
            llm=llm,
            goal="g",
            observation_text="obs",
            last_action={"op": "fill", "ref": 1, "value": "x", "describe": "d"},
            verify_messages=("stagnation: stuck",),
        )
        is None
    )
