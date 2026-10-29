"""Export both OpenAPI schemas to JSON for typed client generation.

Writes ``eval.json`` (FastAPI, exported in-process) and ``records.json``
(Django, via ``manage.py spectacular``) into an output directory. Needs no
``.env`` file or real keys: the records schema is exported with the test
settings module, which generates a throwaway JWT keypair.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    """Repository root, resolved from this file's location (not the cwd)."""
    return Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=repo_root() / ".artifacts" / "openapi",
        help="Directory for eval.json and records.json (default: %(default)s).",
    )
    return parser


def _write_json(path: Path, schema: dict[str, Any]) -> None:
    payload = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    path.write_bytes(payload.encode("utf-8"))


def _export_eval(out_dir: Path) -> None:
    from eval_api.main import create_app

    _write_json(out_dir / "eval.json", create_app().openapi())


def _export_records(out_dir: Path) -> int:
    root = repo_root()
    env = dict(os.environ)
    env["DJANGO_SETTINGS_MODULE"] = "records_test_settings"
    tests_dir = str(root / "services" / "records" / "tests")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = tests_dir if not existing else tests_dir + os.pathsep + existing
    result = subprocess.run(  # noqa: S603  # fixed argv: our own manage.py
        [
            sys.executable,
            str(root / "services" / "records" / "manage.py"),
            "spectacular",
            "--validate",
            "--fail-on-warn",
            "--format",
            "openapi-json",
            "--file",
            str(out_dir / "records.json"),
        ],
        cwd=root,
        env=env,
    )
    if result.returncode != 0:
        print(
            "records schema export failed: manage.py spectacular "
            f"exited with status {result.returncode}",
            file=sys.stderr,
        )
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    _export_eval(out_dir)
    return _export_records(out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
