#!/usr/bin/env python3
"""Small syntax validator used by CI and local pre-push checks."""

from __future__ import annotations

import json
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def validate_python(path: Path) -> None:
    py_compile.compile(str(path), doraise=True)


def validate_json(path: Path) -> None:
    with path.open("r", encoding="utf-8") as f:
        json.load(f)


def validate_yaml(path: Path) -> None:
    with path.open("r", encoding="utf-8") as f:
        list(yaml.safe_load_all(f))


def validate_shell(path: Path) -> None:
    if shutil.which("bash") is None:
        print(f"SKIP {path.relative_to(ROOT)} (bash not found)")
        return
    subprocess.run(["bash", "-n", str(path)], check=True)


def validate_text(path: Path) -> None:
    path.read_text(encoding="utf-8")


def validate(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix == ".py":
        validate_python(path)
    elif suffix == ".json":
        validate_json(path)
    elif suffix in {".yml", ".yaml"}:
        validate_yaml(path)
    elif suffix == ".sh":
        validate_shell(path)
    elif suffix in {".md", ".html", ".css", ".js", ".txt"}:
        validate_text(path)


def default_files() -> list[Path]:
    candidates = [
        ROOT / "scripts/crawl_zol.py",
        ROOT / "scripts/crawl_pconline.py",
        ROOT / "scripts/merge_phones.py",
        ROOT / "scripts/search_root_info.py",
        ROOT / "scripts/proxy_manager.py",
        ROOT / "scripts/setup_proxy_runtime.py",
        ROOT / "scripts/configure_cron_job_org.py",
        ROOT / "scripts/crawl_budget.py",
        ROOT / "scripts/git_sync_progress.sh",
        ROOT / "scripts/merge_progress_json.py",
        ROOT / "scripts/validate_syntax.py",
        ROOT / "scripts/validate_workflow_expectations.py",
        ROOT / ".github/workflows/crawl-zol.yml",
        ROOT / ".github/workflows/crawl-pconline.yml",
        ROOT / ".github/workflows/crawl-trigger.yml",
        ROOT / ".github/workflows/deploy-pages.yml",
        ROOT / ".github/workflows/merge-and-deploy.yml",
        ROOT / ".github/workflows/ci.yml",
        ROOT / "docs/phones/index.html",
        ROOT / "docs/phones/styles.css",
        ROOT / "docs/phones/app.js",
    ]
    return [path for path in candidates if path.exists()]


def main() -> int:
    files = [Path(arg).resolve() for arg in sys.argv[1:]] if len(sys.argv) > 1 else default_files()
    failures: list[str] = []
    for path in files:
        try:
            validate(path)
            print(f"OK {path.relative_to(ROOT)}")
        except Exception as exc:
            failures.append(f"{path.relative_to(ROOT)}: {exc}")

    if failures:
        print("syntax validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
