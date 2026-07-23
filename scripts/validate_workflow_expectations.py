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
SOURCE_BY_WORKFLOW = {
    "crawl-zol.yml": "zol",
    "crawl-pconline.yml": "pconline",
    "crawl-cnmo.yml": "cnmo",
}


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
    source = SOURCE_BY_WORKFLOW[path.name]
    job = next(iter(data["jobs"].values()))
    steps = job["steps"]
    upload = next((step for step in steps if step.get("id") == "upload_data"), {})
    dispatch = next((step for step in steps if step.get("name") == "触发合并分析工作流"), {})
    commit = next((step for step in steps if step.get("name") == "Mark crawl complete and commit"), {})
    early = next((step for step in steps if step.get("name") == "Upload crawl data (early, after step1)"), {})

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
        assert_condition(
            'python3 scripts/validate_cnmo_dataset.py "$DATA_FILE" --debug' in text
            and 'python3 scripts/validate_cnmo_dataset.py "$DATA_FILE"' in text,
            "crawl-cnmo.yml does not use alias-aware CNMO dataset validation",
            errors,
        )
    assert_condition("steps.check_done.outputs.done" not in text, f"{path.name} references undefined check_done step", errors)
    assert_condition(
        data.get("concurrency", {}).get("group") == f"{source}-phone-crawl-${{{{ github.ref }}}}",
        f"{path.name} concurrency must not split by run_profile",
        errors,
    )
    assert_condition(
        'if [ "$DEBUG_LIMIT" = "0" ]; then DEBUG_LIMIT=30; fi' in text
        and '[[ "$DEBUG_LIMIT" =~ ^[0-9]+$ ]]' in text
        and '[ "$DEBUG_LIMIT" -lt 20 ]' in text
        and '[ "$DEBUG_LIMIT" -gt 30 ]' in text,
        f"{path.name} missing fail-closed debug limit 20..30 with 0 -> 30",
        errors,
    )
    assert_condition(
        f"rm -rf crawl_state/{source}" in text
        and f"rm -f data/{source}_phones_*.json data/{source}_phones_*.csv" in text
        and f"{source}_debug_current_period" in text,
        f"{path.name} does not isolate debug progress state",
        errors,
    )
    assert_condition(
        "github.event.inputs.debug_mode != 'true'" in str(commit.get("if", "")),
        f"{path.name} debug run can execute final git/progress sync",
        errors,
    )
    assert_condition(
        "github.event.inputs.debug_mode != 'true'" in str(early.get("if", "")),
        f"{path.name} debug run can upload stable early state",
        errors,
    )
    if source in {"zol", "pconline"}:
        assert_condition(
            'if [ "${{ github.event.inputs.debug_mode || \'false\' }}" != "true" ]; then' in text,
            f"{path.name} exit 10 branch can sync debug progress",
            errors,
        )
    upload_with = upload.get("with", {})
    artifact_name = str(upload_with.get("name", ""))
    assert_condition(
        f"{source}-phone-debug-data-{{0}}-{{1}}" in artifact_name
        and f"{source}-phone-data-{{0}}-{{1}}" in artifact_name,
        f"{path.name} final artifact names are not disjoint run/attempt names",
        errors,
    )
    assert_condition(
        upload_with.get("if-no-files-found") == "error",
        f"{path.name} final artifact must fail when files are missing",
        errors,
    )
    if source == "cnmo":
        assert_condition(
            "steps.validate_data.outputs.has_data == 'true'" in str(upload.get("if", "")),
            f"{path.name} final artifact upload is not gated by valid CNMO data",
            errors,
        )
    dispatch_if = str(dispatch.get("if", ""))
    dispatch_run = str(dispatch.get("run", ""))
    assert_condition(
        "steps.upload_data.outcome == 'success'" in dispatch_if
        and "steps.validate_data.outputs.has_data == 'true'" in dispatch_if,
        f"{path.name} merge dispatch is not gated by validation and upload success",
        errors,
    )
    for required_input in ("debug_mode", "crawler_run_id", "crawler_run_attempt", "trigger_source", "trigger_date"):
        assert_condition(
            f'"{required_input}"' in dispatch_run,
            f"{path.name} merge dispatch missing {required_input}",
            errors,
        )


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
    data = load_yaml(path)
    text = path.read_text(encoding="utf-8")
    push_branches = data.get(True, {}).get("push", {}).get("branches", [])
    assert_condition(push_branches == ["main"], "merge-and-deploy.yml push must be limited to main", errors)
    assert_condition(
        'CNMO_DONE="crawl_state/cnmo_${CRAWL_PERIOD}.done"' in text
        and '[ -f "$CNMO_DONE" ]' in text
        and "CNMO完成:" in text,
        "merge half-month completion must require CNMO done marker",
        errors,
    )
    assert_condition(
        "timeout --signal=KILL 27m python scripts/ai_verify_root_status.py" in text,
        "merge-and-deploy.yml missing AI verification hard timeout",
        errors,
    )
    assert_condition(
        "scripts/preserve_publish_baseline.py" in text,
        "merge-and-deploy.yml must carry published identities into each candidate",
        errors,
    )
    inputs = data.get(True, {}).get("workflow_dispatch", {}).get("inputs", {})
    for required_input in ("debug_mode", "crawler_run_id", "crawler_run_attempt", "trigger_source", "trigger_date"):
        assert_condition(required_input in inputs, f"merge-and-deploy.yml missing input {required_input}", errors)
    assert_condition("phone-data*" not in text, "merge stable artifact selection still uses wildcard", errors)
    assert_condition("gh api --paginate" in text and "PERIOD_START" in text, "merge does not paginate current half-month stable runs", errors)
    assert_condition(
        "prior-period-phone-data" not in text,
        "merge must retain repository stable history while adding current-half-month artifacts",
        errors,
    )
    for source in ("zol", "pconline", "cnmo"):
        assert_condition(
            f'"{source}-phone-data-${{run_id}}-${{run_attempt}}"' not in text
            and f'artifact_name="${{source}}-phone-data-${{run_id}}-${{run_attempt}}"' in text,
            f"merge does not construct exact stable artifact for {source}",
            errors,
        )
    for marker in (
        'str(run.get("path", "")).split("@", 1)[0]',
        "run.get(\"run_attempt\")",
        "debug_count",
        "selected_debug=\"data/${CRAWLER_RUN_ID}_",
    ):
        assert_condition(marker in text, f"merge missing exact debug selection marker: {marker}", errors)
    commit = next(
        step for step in data["jobs"]["merge-data"]["steps"] if step.get("name") == "提交合并产物到仓库"
    )
    assert_condition(
        "github.event.inputs.debug_mode != 'true'" in str(commit.get("if", "")),
        "debug merge can commit merged output",
        errors,
    )
    assert_condition(
        text.count("scripts/verify_publish_superset.py") == 2
        and text.count("https://phones.jiucai.eu.org/data/latest.json") == 3
        and "if: steps.validate.outputs.ready == 'true'\n        env:" in text
        and "if: github.event.inputs.debug_mode == 'true'" not in text[text.index("- name: 部署前再次校验线上基线超集"):],
        "publish superset guard must run for every release before artifact and before Pages deploy",
        errors,
    )
    publish_guard_position = text.index("- name: 发布前校验线上基线超集")
    preserve_position = text.index("- name: 保留线上基线身份")
    commit_position = text.index("- name: 提交合并产物到仓库")
    upload_position = text.index("- name: 上传合并产物")
    result_position = text.index("- name: 检查合并结果")
    assert_condition(
        preserve_position < result_position < publish_guard_position < commit_position < upload_position,
        "baseline preservation and publish guard must run before commit and artifact upload",
        errors,
    )
    release = data["jobs"]["create-release"]
    deploy = data["jobs"]["deploy-pages"]
    assert_condition("github.run_id" in text[text.index("tag_name:"):text.index("name: 手机数据")], "release tag missing merge run_id", errors)
    assert_condition("create-release" in deploy.get("needs", []), "deploy-pages does not need create-release", errors)
    assert_condition("needs.create-release.result == 'success'" in str(deploy.get("if", "")), "deploy-pages does not require successful release", errors)
    assert_condition(
        text.index("- name: 上传合并产物") < text.index("  create-release:") < text.index("  deploy-pages:"),
        "publish order must be merge artifact -> Release -> Pages",
        errors,
    )


def check_deploy_pages_workflow(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    rows_marker = 'if [ "$ROWS" -lt 10 ]; then'
    date_marker = 'DATE=$(basename "$MERGED_JSON"'
    has_rows_marker = rows_marker in text
    has_date_marker = date_marker in text
    tiny_release_block = ""
    if has_rows_marker and has_date_marker:
        tiny_release_block = text[text.index(rows_marker):text.index(date_marker)]
    assert_condition(
        has_rows_marker
        and has_date_marker
        and "continue" in tiny_release_block,
        "deploy-pages.yml must skip releases with fewer than 10 merged rows",
        errors,
    )
    assert_condition(
        "scripts/verify_publish_superset.py /tmp/phones-pages-baseline.json site/data/latest.json" in text
        and "https://phones.jiucai.eu.org/data/latest.json" in text,
        "deploy-pages.yml must verify candidate latest.json is a superset of current Pages data",
        errors,
    )
    assert_condition(
        "--pattern 'merged_phones_*.json'" in text
        and "--pattern 'merged_phones_*.csv'" in text
        and "release-files/merged_phones_*.json" in text
        and "release-files/merged_phones_*.csv" in text
        and "release-files/data/merged_phones_" not in text,
        "deploy-pages.yml must use the flat merged_phones release asset paths",
        errors,
    )
    assert_condition(
        "python scripts/verify_publish_superset.py docs/phones/data/latest.json site/data/latest.json" in text
        and "拒绝发布以避免缩小稳定数据" in text
        and "跳过超集校验" not in text,
        "deploy-pages.yml must fail closed or use repository baseline when Pages baseline cannot be fetched",
        errors,
    )


def main() -> int:
    errors: list[str] = []
    for path in CRAWLER_WORKFLOWS:
        check_crawler_workflow(path, errors)
    check_trigger(ROOT / ".github/workflows/crawl-trigger.yml", errors)
    check_budget_script(ROOT / "scripts/crawl_budget.py", errors)
    check_merge_workflow(ROOT / ".github/workflows/merge-and-deploy.yml", errors)
    check_deploy_pages_workflow(ROOT / ".github/workflows/deploy-pages.yml", errors)
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
