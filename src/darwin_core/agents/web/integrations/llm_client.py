from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"


def _extract_json_object(text: str) -> dict[str, Any]:
    """Parse the first JSON object (or first useful object inside a root array) from *text*.

    Uses :meth:`json.JSONDecoder.raw_decode` so trailing prose or a second JSON value does not
    break parsing (fixes ``Extra data`` from :func:`json.loads` on substring).
    """
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    decoder = json.JSONDecoder()
    n = len(text)
    for i in range(n):
        ch = text[i]
        if ch not in "{[":
            continue
        try:
            obj, _end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if ch == "{" and isinstance(obj, dict):
            return obj
        if ch == "[" and isinstance(obj, list):
            for item in obj:
                if not isinstance(item, dict):
                    continue
                if "action" in item and isinstance(item.get("action"), dict):
                    return item
                if item.get("op") is not None:
                    return {"thought": str(item.get("thought", "")), "action": item}
            for item in obj:
                if isinstance(item, dict):
                    return item
            continue
    raise ValueError("No JSON object found in model output.")


@dataclass(frozen=True)
class LLMTurnTranscript:
    """One planner call: prompts and model output for artifact logs."""

    model: str
    messages: list[dict[str, Any]]
    assistant_raw: str
    assistant_parsed: dict[str, Any]
    openrouter_id: str | None
    openrouter_model: str | None
    usage: dict[str, Any] | None
    finish_reason: str | None


class OpenRouterClient:
    """Minimal OpenRouter chat client (no darwin_core dependency)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
        self.timeout_seconds = timeout_seconds
        self.referer = os.getenv("OPENROUTER_HTTP_REFERER")
        self.title = os.getenv("OPENROUTER_X_TITLE", "darwin-web")

        if not self.api_key:
            raise ValueError("Missing OPENROUTER_API_KEY.")

    def chat_planner_turn(
        self,
        user_prompt: str,
        *,
        system_prompt: str,
        vision_png_path: Path | None = None,
    ) -> LLMTurnTranscript:
        """Call OpenRouter once; return parsed planner JSON plus a full transcript for logging.

        When *vision_png_path* is set and exists, the user message is multimodal (text + image)
        per OpenAI-compatible chat completions.
        """
        user_content: str | list[dict[str, Any]]
        if vision_png_path is not None and vision_png_path.is_file():
            raw = vision_png_path.read_bytes()
            b64 = base64.standard_b64encode(raw).decode("ascii")
            user_content = [
                {"type": "text", "text": user_prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                },
            ]
        else:
            user_content = user_prompt

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
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
        choice0 = choices[0] if isinstance(choices[0], dict) else {}
        content = choice0.get("message", {}).get("content")
        if not isinstance(content, str):
            raise RuntimeError("OpenRouter response content missing.")
        parsed = _extract_json_object(content)
        usage = data.get("usage")
        return LLMTurnTranscript(
            model=self.model,
            messages=list(messages),
            assistant_raw=content,
            assistant_parsed=dict(parsed),
            openrouter_id=data.get("id") if isinstance(data.get("id"), str) else None,
            openrouter_model=data.get("model") if isinstance(data.get("model"), str) else None,
            usage=dict(usage) if isinstance(usage, dict) else None,
            finish_reason=choice0.get("finish_reason")
            if isinstance(choice0.get("finish_reason"), str)
            else None,
        )

    def chat_json(self, user_prompt: str, *, system_prompt: str) -> dict[str, Any]:
        """Backward-compatible: parsed planner object only."""
        return dict(self.chat_planner_turn(user_prompt, system_prompt=system_prompt).assistant_parsed)
