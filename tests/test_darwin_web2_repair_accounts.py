from __future__ import annotations

from pathlib import Path

import yaml

from darwin_web2.accounts import append_account_record, default_accounts_path
from darwin_web2.repair import write_repair_marker


def test_append_account_record_jsonl(tmp_path: Path) -> None:
    p = tmp_path / "a.jsonl"
    append_account_record(p, {"goal": "x", "ok": True})
    append_account_record(p, {"goal": "y", "ok": False})
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert Path(default_accounts_path()).name == "accounts.jsonl"


def test_write_repair_marker(tmp_path: Path) -> None:
    pb = tmp_path / "playbook.yaml"
    pb.write_text("recipe_version: 2\ngoal: x\nsteps: []\n", encoding="utf-8")
    out = write_repair_marker(pb, failed_index=0, error="boom", page_url="https://e/")
    assert out.exists()
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["failed_step_index"] == 0
    assert data["error"] == "boom"
