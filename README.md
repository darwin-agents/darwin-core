# Darwin Core

Darwin Core is a state-of-the-art, resilient, and production-ready web agent orchestration framework. Built on top of Playwright, OpenRouter, and Browser Use Cloud, Darwin Core empowers autonomous AI agents to navigate the web, interact with complex UIs, and accomplish high-level user tasks—all while possessing built-in self-correction capabilities.

## Key Features

- **Resilient Web Automation**: Uses a dynamic `observe → plan → execute → verify` loop that gracefully handles complex, dynamic DOMs, single-page applications (SPAs), and unpredictable UI updates.
- **Self-Healing & Reflection**: Actively tracks state stagnation and layout fingerprints. When the agent detects an error or dead-end, it enters a `reflect` cycle to self-diagnose and attempt alternative interactions.
- **Multimodal Context**: Leverages both comprehensive accessibility trees (ARIA) and visual screenshots (Vision) to feed the LLM a rich understanding of the viewport.
- **Human-in-the-Loop (HIL)**: Full Telegram integration. When the agent encounters impassable captchas or SMS OTP walls, it pauses execution and sends a screenshot directly to your phone via Telegram, waiting for you to provide the code or solve the challenge.
- **Dynamic Playbooks & Recipes**: Capable of executing structured YAML playbooks with built-in password/username generation (`$GENHASH`) and account credential saving.

## Project Architecture

Darwin Core's web agent lives under `src/darwin_core/agents/web/` in specialized sub-packages:

- `core/`: The main orchestration loop (`loop.py`), CLI interfaces, and prompt policies.
- `browser/`: DOM extraction, Playwright session bridging, and layout fingerprinting.
- `execution/`: Step coercion and execution dispatching.
- `intelligence/`: Heuristic hints, validation logic, self-repair loops, and captcha detection.
- `integrations/`: OpenRouter, Telegram HIL, and dynamic email provider ranking.
- `playbook/`: YAML definition parsing and execution recording.
- `security/`: Redaction engines to scrub secrets from logs and artifacts.

## Quickstart

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) or `poetry` for dependency management.

### Configuration

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
2. Add your API Keys (`OPENROUTER_API_KEY`, `BROWSER_USE_API_KEY`, etc.).

### Usage

Start the Browser Use bridge (in another terminal), then run the web agent with a natural-language goal:

```bash
uv run darwin-web-agent "Sign up for a newsletter on example.com"
```

Replay a saved v2 playbook:

```bash
uv run darwin-web-replay artifacts/darwin-web/playbook.yaml
```

## Testing

The project maintains a rigorous, organized test suite (`pytest`) covering 120+ cases.

```bash
uv run pytest tests/ -v
```
