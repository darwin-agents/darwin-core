# Changelog

All notable changes to Darwin Core will be documented in this file.

## [0.1.0] - Initial Release

### Core Orchestration
- **Resilient Web Agent Loop:** Implemented a robust `observe → plan → execute → verify` lifecycle for interacting with highly dynamic Single Page Applications.
- **Self-Healing & Reflection:** Added automated state stagnation detection. The agent automatically detects when an action fails to advance the page and triggers a secondary `reflect` LLM pass to self-correct.
- **Multimodal Observation:** Integrated full DOM parsing, Playwright accessibility tree (ARIA) generation, and visual screenshot attachments for the planner LLM.
- **Automated Unsticking:** Included fallback logic to automatically bypass cookie consent banners and predictable blockers without consuming LLM reasoning tokens.

### Human-in-the-Loop (HIL)
- **Telegram Integration:** Built a complete Telegram bot interface to pause agent execution when encountering CAPTCHAs or SMS OTP walls.
- **Interactive Prompts:** The agent forwards screenshots of the blockage to Telegram and resumes execution using the human's natural language reply or OTP code.
- **QR Code Decoding:** Added optional local QR decoding for HIL screenshots to send clickable HTTP links directly to Telegram.

### Playbooks & Execution
- **YAML Playbooks:** Implemented a recording and replay engine that saves successful agent traces into structured YAML playbooks.
- **Dynamic Credential Generation (`$GENHASH`):** Added deterministic, on-the-fly password and username generation for automated account signups, mapped directly to target domains.
- **Credential Storage:** Automated extraction and append-only saving of successful account creations to local `accounts.jsonl`.
- **Advanced Selectors:** Built resilient Playwright locator logic (handling text, placeholders, test-ids, and fallback ARIA roles) to interact with forms accurately.

### Integrations & Environment
- **Browser Use Bridge:** Integrated cloud-based browser session management (connect, reconnect, and automatic release on 429 errors).
- **OpenRouter LLM Client:** Added a dedicated client for OpenRouter, handling JSON validation, schema coercion, and robust error retries.
- **Email Provider Ranking:** Built a deterministic email provider routing system to automatically rotate through configured email domains (e.g., `config/emails.json`) during mass signups.

### Security
- **Artifact Redaction:** Implemented a comprehensive secrets-scrubbing engine to proactively redact `$GENHASH_PW` and explicit password fields from logs, DOM snapshots, and LLM turn artifacts.
