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
    ROOT / ".github/workflows/crawl-cnmo.yml",
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
    schedules = data.get(True, {}).get("schedule", [])

    assert_condition(not schedules, f"{path.name} should not rely on GitHub Actions schedule", errors)
    assert_condition("WORKFLOW_START_EPOCH" in text, f"{path.name} missing workflow start budget", errors)
    assert_condition("MAX_WORKFLOW_SECONDS" in text, f"{path.name} missing max workflow budget", errors)
    assert_condition("PROGRESS_COMMIT_BUFFER_SECONDS" in text, f"{path.name} missing progress commit buffer", errors)
    assert_condition("WINDOW_END_BUFFER_SECONDS" in text, f"{path.name} missing window end buffer", errors)
    assert_condition("scripts/crawl_budget.py configure" in text, f"{path.name} does not use shared crawl window budget", errors)
    assert_condition("scripts/crawl_budget.py clamp" in text, f"{path.name} does not clamp by combined budget", errors)
    assert_condition("EXIT_CODE=$?" in text, f"{path.name} does not capture crawler exit code", errors)
    assert_condition("[ $EXIT_CODE -eq 10 ]" in text, f"{path.name} does not treat exit 10 as resumable", errors)
    assert_condition("scripts/git_sync_progress.sh" in text, f"{path.name} does not use robust progress sync", errors)
    assert_condition(
        "*** secrets.GITHUB_TOKEN }}" not in text,
        f"{path.name} contains a corrupted GITHUB_TOKEN expression",
        errors,
    )
    if path.name == "crawl-cnmo.yml":
        expected_fields = "key_fields=['处理器','内存','存储','屏幕','电池类型','后置相机','上市时间']"
        assert_condition(expected_fields in text, "crawl-cnmo.yml does not validate CNMO schema fields", errors)
    assert_condition("steps.check_done.outputs.done" not in text, f"{path.name} references undefined check_done step", errors)


def check_trigger(path: Path, errors: list[str]) -> None:
    data = load_yaml(path)
    text = path.read_text(encoding="utf-8")
    dispatch_types = data.get(True, {}).get("repository_dispatch", {}).get("types", [])

    assert_condition("trigger-crawl" in dispatch_types, "crawl-trigger.yml missing trigger-crawl dispatch", errors)
    assert_condition("crawl-zol.yml" in text, "crawl-trigger.yml does not trigger ZOL", errors)
    assert_condition("crawl-pconline.yml" in text, "crawl-trigger.yml does not trigger PConline", errors)
    assert_condition("crawl-cnmo.yml" in text, "crawl-trigger.yml does not trigger CNMO", errors)
    assert_condition("max_pages" not in text, "crawl-trigger.yml passes unsupported max_pages to CNMO", errors)
    assert_condition("08:00-12:30" in text, "crawl-trigger.yml missing morning window text", errors)
    assert_condition("13:00-22:00" in text, "crawl-trigger.yml missing afternoon window text", errors)


def check_budget_script(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    assert_condition('"afternoon": (13 * 60, 22 * 60)' in text, "crawl_budget.py missing 13:00-22:00 afternoon window", errors)
    assert_condition("MAX_WORKFLOW_SECONDS" in text, "crawl_budget.py missing action budget", errors)
    assert_condition("PROGRESS_COMMIT_BUFFER_SECONDS" in text, "crawl_budget.py missing progress buffer", errors)


def check_merge_workflow(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    assert_condition(
        "timeout --signal=KILL 27m python scripts/ai_verify_root_status.py" in text,
        "merge-and-deploy.yml missing AI verification hard timeout",
        errors,
    )


def main() -> int:
    errors: list[str] = []
    for path in CRAWLER_WORKFLOWS:
        check_crawler_workflow(path, errors)
    check_trigger(ROOT / ".github/workflows/crawl-trigger.yml", errors)
    check_budget_script(ROOT / "scripts/crawl_budget.py", errors)
    check_merge_workflow(ROOT / ".github/workflows/merge-and-deploy.yml", errors)
    assert_condition((ROOT / "scripts/configure_cron_job_org.py").exists(), "missing cron-job.org configuration script", errors)

    if errors:
        print("workflow expectation check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("workflow expectation check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
