"""Tests for scripts/export_openapi.py (offline schema export, no .env needed)."""

import json
from pathlib import Path

from export_openapi import main


def test_exports_both_schemas(tmp_path: Path) -> None:
    assert main(["--out-dir", str(tmp_path)]) == 0

    eval_schema = json.loads((tmp_path / "eval.json").read_text(encoding="utf-8"))
    assert "/health" in eval_schema["paths"]
    assert "/api/eval/me" in eval_schema["paths"]

    records_schema = json.loads((tmp_path / "records.json").read_text(encoding="utf-8"))
    assert "/api/records/auth/token/" in records_schema["paths"]
    assert "/api/records/projects/" in records_schema["paths"]
