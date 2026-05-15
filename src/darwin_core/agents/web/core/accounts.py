"""Append-only account / run outcomes (JSON lines)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def default_accounts_path() -> Path:
    import os

    raw = os.getenv("DARWIN_WEB2_ACCOUNTS_PATH", "artifacts/darwin-web2/accounts.jsonl")
    return Path(raw)


def append_account_record(path: Path, record: dict[str, Any]) -> None:
    """Append one JSON object per line (UTF-8)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
