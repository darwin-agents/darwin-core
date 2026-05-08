from __future__ import annotations

import os
from typing import Any

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"


class OpenRouterService:
    """Small service wrapper for OpenRouter chat completions."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 30.0,
        referer: str | None = None,
        title: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
        self.timeout_seconds = timeout_seconds
        self.referer = referer or os.getenv("OPENROUTER_HTTP_REFERER")
        self.title = title or os.getenv("OPENROUTER_X_TITLE", "darwin-core")

        if not self.api_key:
            raise ValueError("Missing OPENROUTER_API_KEY.")

    def chat(self, prompt: str, *, system_prompt: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.referer:
            headers["HTTP-Referer"] = self.referer
        if self.title:
            headers["X-Title"] = self.title

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(OPENROUTER_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("OpenRouter response had no choices.")

        message = choices[0].get("message", {})
        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError("OpenRouter response content is missing or invalid.")
        return content

