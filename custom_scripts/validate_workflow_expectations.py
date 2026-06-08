#!/usr/bin/env python3
"""Static checks for phone crawler workflow guardrails."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CRAWLER_WORKFLOWS = [
    ROOT / ".github/workflows/crawl-zol.yml",
    ROOT / ".github/workflows/crawl-pconline.yml",
]


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def assert_condition(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def check_crawler_workflow(path: Path, errors: list[str]) -> None:
    data = load_yaml(path)
    text = path.read_text(encoding="utf-8")
    schedules = [item.get("cron") for item in data.get(True, {}).get("schedule", [])]

    assert_condition(schedules, f"{path.name} missing schedule cron", errors)
    assert_condition("WORKFLOW_START_EPOCH" in text, f"{path.name} missing workflow start budget", errors)
    assert_condition("MAX_WORKFLOW_SECONDS" in text, f"{path.name} missing max workflow budget", errors)
    assert_condition("PROGRESS_COMMIT_BUFFER_SECONDS" in text, f"{path.name} missing progress commit buffer", errors)
    assert_condition("EXIT_CODE=$?" in text, f"{path.name} does not capture crawler exit code", errors)
    assert_condition("[ $EXIT_CODE -eq 10 ]" in text, f"{path.name} does not treat exit 10 as resumable", errors)
    assert_condition("custom_scripts/git_sync_progress.sh" in text, f"{path.name} does not use robust progress sync", errors)
    assert_condition("steps.check_done.outputs.done" not in text, f"{path.name} references undefined check_done step", errors)
    assert_condition("不在允许爬取窗口" in text, f"{path.name} missing crawl window skip guard", errors)


def main() -> int:
    errors: list[str] = []
    for path in CRAWLER_WORKFLOWS:
        check_crawler_workflow(path, errors)

    if errors:
        print("workflow expectation check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("workflow expectation check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
