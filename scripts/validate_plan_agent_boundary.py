#!/usr/bin/env python3
"""Enforce the boundary between Plan credentials and Python model callers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLAN_KEY_NAMES = {
    "VOLCENGINE_AGENTPLAN_API_KEY",
    "KIMI_CODINGPLAN_API_KEY",
    "MINIMAX_CODING_PLAN_API_KEY",
    "TENCENT_TOKENPLAN_API_KEY",
}
PLAN_KEY_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?P<name>[A-Za-z][A-Za-z0-9_]*(?:CODINGPLAN|CODING_PLAN|AGENTPLAN|AGENT_PLAN|TOKENPLAN|TOKEN_PLAN|PLAN)_(?:API_KEY|KEY|TOKEN|SECRET))(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)
DIRECT_PLAN_MARKERS = (
    "/api/plan/",
    "api.kimi.com/coding",
)
EXPECTED_AGENT_STEPS = {}
AGENT_VERSION = "opencode-ai@latest"
READ_ONLY_PERMISSIONS = {
    "*": "deny",
    "read": "allow",
    "edit": "deny",
    "bash": "deny",
    "webfetch": "deny",
    "task": "deny",
    "question": "deny",
    "external_directory": "deny",
}


def _is_plan_key(value: str) -> bool:
    return bool(PLAN_KEY_PATTERN.fullmatch(value.strip()))


def _plan_key_matches(text: str) -> list[re.Match[str]]:
    return list(PLAN_KEY_PATTERN.finditer(text))


def _step_blocks(text: str) -> list[tuple[str, str, int, int]]:
    pattern = re.compile(
        r"(?ms)^(?P<indent>[ \t]+)- name: (?P<name>[^\n]+)\n"
        r"(?P<body>.*?)(?=^(?P=indent)- name: |\Z)"
    )
    return [
        (match.group("name").strip(), match.group(0), match.start(), match.end())
        for match in pattern.finditer(text)
    ]


def _position_is_in_step_env(block: str, position: int) -> bool:
    """Return whether a raw secret occurrence is under that step's env mapping."""
    env_match = re.search(r"(?m)^(?P<indent>[ \t]+)env:\s*$", block)
    if not env_match:
        return False
    env_indent = len(env_match.group("indent"))
    start = env_match.end()
    if start < len(block) and block[start] == "\n":
        start += 1
    cursor = start
    while cursor < len(block):
        line_end = block.find("\n", cursor)
        if line_end < 0:
            line_end = len(block)
        line = block[cursor:line_end]
        if line.strip() and len(line) - len(line.lstrip(" \t")) <= env_indent:
            return False
        if cursor <= position < line_end:
            return True
        cursor = line_end + 1
    return False


def _plan_keys_in_env(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [str(key) for key in value if _is_plan_key(str(key))]


def _error_prefix(path: Path, job_name: str, name: str) -> str:
    return f"{path.name}:{job_name}:{name}"


def _validate_agent_step(
    path: Path,
    job_name: str,
    name: str,
    step: dict[str, Any],
    expected_model: str | None,
    errors: list[str],
) -> None:
    prefix = _error_prefix(path, job_name, name)
    run = str(step.get("run") or "").strip()
    env = step.get("env") if isinstance(step.get("env"), dict) else {}
    plan_keys = _plan_keys_in_env(env)

    if "Agent" not in name or not re.search(r"\bopencode\s+run\b", run):
        errors.append(f"{prefix}: Plan key is not isolated to a read-only OpenCode Agent step")
        return
    if "--pure" not in run or "--agent plan" not in run or "--model" not in run:
        errors.append(f"{prefix}: Agent step must use --pure --agent plan --model")
    if '--dir "$RUNNER_TEMP/opencode-agent"' not in run:
        errors.append(f"{prefix}: Agent step must run in the isolated temporary directory")
    if "--file prompt.md" not in run:
        errors.append(f"{prefix}: Agent step must read the copied prompt file")
    if "\n" in run or any(operator in run for operator in (";", "&&", "||", "|")):
        errors.append(f"{prefix}: Agent step must contain only one OpenCode command")
    if not re.fullmatch(r"opencode\s+run\b.*>\s*\S+", run, flags=re.DOTALL):
        errors.append(f"{prefix}: Agent step must redirect one OpenCode command output")
    forbidden = re.search(r"\b(?:python3?|npm|npx|curl|wget|tee|head)\b|\$GITHUB_ENV", run)
    if forbidden:
        errors.append(f"{prefix}: Plan Agent step also runs {forbidden.group(0)}")
    if len(plan_keys) != 1:
        errors.append(f"{prefix}: Agent step must expose exactly one Plan key through env")
        return

    model_match = re.search(r"--model\s+(\S+)", run)
    model = model_match.group(1) if model_match else ""
    if expected_model and model != expected_model:
        errors.append(f"{prefix}: Plan key is not bound to the expected provider/model {expected_model}")
        model = expected_model
    if "/" not in model:
        errors.append(f"{prefix}: Agent model must use provider/model syntax")
        return
    provider_name, model_name = model.split("/", 1)

    raw_config = env.get("OPENCODE_CONFIG_CONTENT")
    if not isinstance(raw_config, str):
        errors.append(f"{prefix}: Agent step must provide an inline minimal OpenCode config")
        return
    try:
        config = json.loads(raw_config)
    except (TypeError, json.JSONDecodeError) as exc:
        errors.append(f"{prefix}: OPENCODE_CONFIG_CONTENT is not strict JSON: {exc}")
        return
    if config.get("autoupdate") is not False:
        errors.append(f"{prefix}: OpenCode autoupdate must be disabled")
    if "plugin" in config or "mcp" in config:
        errors.append(f"{prefix}: minimal Agent config must not load plugins or MCP servers")
    providers = config.get("provider")
    if not isinstance(providers, dict) or set(providers) != {provider_name}:
        errors.append(f"{prefix}: Agent config must contain exactly provider {provider_name}")
    else:
        provider = providers[provider_name]
        if not isinstance(provider, dict):
            errors.append(f"{prefix}: Agent provider config is not an object")
        else:
            options = provider.get("options")
            plan_key = plan_keys[0]
            expected_api_key = "{env:" + plan_key + "}"
            if not isinstance(options, dict) or options.get("apiKey") != expected_api_key:
                errors.append(f"{prefix}: Agent provider must read its Plan key from env")
            models = provider.get("models")
            if not isinstance(models, dict) or set(models) != {model_name}:
                errors.append(f"{prefix}: Agent provider must expose only model {model_name}")

    agent_plan = config.get("agent", {}).get("plan") if isinstance(config.get("agent"), dict) else None
    if not isinstance(agent_plan, dict) or agent_plan.get("model") != model:
        errors.append(f"{prefix}: plan agent model must match the CLI model")
    elif agent_plan.get("permission") != READ_ONLY_PERMISSIONS:
        errors.append(f"{prefix}: plan agent permissions must be read-only")
    if config.get("permission") != READ_ONLY_PERMISSIONS:
        errors.append(f"{prefix}: default OpenCode permissions must be read-only")


def _check_workflow(path: Path, errors: list[str], root: Path = ROOT) -> None:
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        errors.append(f"{path.name}: YAML parse failed: {exc}")
        return
    if not isinstance(data, dict):
        errors.append(f"{path.name}: workflow root is not a mapping")
        return

    top_plan = _plan_keys_in_env(data.get("env"))
    if top_plan:
        errors.append(f"{path.name}: Plan key is present in workflow-level env: {', '.join(top_plan)}")

    jobs = data.get("jobs") or {}
    plan_step_count = 0
    if isinstance(jobs, dict):
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            job_plan = _plan_keys_in_env(job.get("env"))
            if job_plan:
                errors.append(f"{path.name}:{job_name}: Plan key is present in job-level env: {', '.join(job_plan)}")
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                step_plan = _plan_keys_in_env(step.get("env"))
                if not step_plan:
                    continue
                plan_step_count += 1
                relative = path.relative_to(root).as_posix()
                expected = EXPECTED_AGENT_STEPS.get(relative)
                _validate_agent_step(
                    path,
                    str(job_name),
                    str(step.get("name") or ""),
                    step,
                    expected["model"] if expected else None,
                    errors,
                )
                for field_name in ("run", "name", "uses", "with"):
                    field_value = str(step.get(field_name) or "")
                    if _plan_key_matches(field_value):
                        errors.append(
                            f"{path.name}:{job_name}:{step.get('name') or ''}: Plan key must not be written in {field_name}; use Agent env"
                        )

    blocks = _step_blocks(text)
    for match in _plan_key_matches(text):
        containing = [block for block in blocks if block[2] <= match.start() < block[3]]
        if len(containing) != 1:
            errors.append(f"{path.name}: {match.group('name')} occurs outside a workflow step")
            continue
        body = containing[0][1]
        if not _position_is_in_step_env(body, match.start() - containing[0][2]):
            errors.append(f"{path.name}: {match.group('name')} must be supplied through an Agent step env")
        elif "opencode run" not in body or "--agent plan" not in body:
            errors.append(f"{path.name}: {match.group('name')} occurs outside the OpenCode Agent step")

    relative = path.relative_to(root).as_posix()
    expected = EXPECTED_AGENT_STEPS.get(relative)
    if expected:
        matching = [
            block
            for block in blocks
            if expected["key"] in block[1] and "opencode run" in block[1] and "--agent plan" in block[1]
        ]
        if len(matching) != 1:
            errors.append(f"{path.name}: expected exactly one Agent step for {expected['key']}, found {len(matching)}")
        elif expected["model"] not in matching[0][1]:
            errors.append(f"{path.name}: Plan key is not bound to the expected provider/model {expected['model']}")
    if plan_step_count and AGENT_VERSION not in text:
        errors.append(f"{path.name}: Plan Agent workflow must install {AGENT_VERSION} (auto-upgrade, never a pinned version)")


def validate_repository(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for relative in EXPECTED_AGENT_STEPS:
        path = root / relative
        if not path.is_file():
            errors.append(f"{relative}: expected workflow is missing")
    workflow_dir = root / ".github" / "workflows"
    if workflow_dir.is_dir():
        for path in sorted(workflow_dir.glob("*.y*ml")):
            _check_workflow(path, errors, root)

    scripts_dir = root / "scripts"
    if scripts_dir.is_dir():
        validator_path = root / "scripts" / Path(__file__).name
        for path in sorted(scripts_dir.rglob("*.py")):
            if path == validator_path:
                continue
            text = path.read_text(encoding="utf-8")
            lowered = text.lower()
            for marker in DIRECT_PLAN_MARKERS:
                if marker in lowered:
                    errors.append(f"{path.relative_to(root)}: direct Plan endpoint is present: {marker}")
            for match in _plan_key_matches(text):
                errors.append(f"{path.relative_to(root)}: production Python script references Plan key {match.group('name')}")
    return errors


def main() -> int:
    errors = validate_repository()
    if errors:
        print("Plan/Agent boundary validation failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Plan/Agent boundary validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
