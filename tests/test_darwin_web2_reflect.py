from __future__ import annotations

from darwin_web2.reflect import reflect_repair_action


class _StubLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def chat_json(self, user_prompt: str, *, system_prompt: str) -> dict:
        return dict(self.payload)


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
