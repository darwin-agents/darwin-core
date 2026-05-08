import pytest

from darwin_core.services.llm.openrouter import OpenRouterService


def test_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError):
        OpenRouterService()

