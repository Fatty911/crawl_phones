#!/usr/bin/env python3
"""Prevent crawler data and long-lived artifacts from returning to Git."""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def stages_data_directory(text: str) -> bool:
    logical_lines: list[str] = []
    pending = ""
    for physical_line in text.splitlines():
        line = physical_line.strip()
        pending = f"{pending} {line}".strip() if pending else line
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        logical_lines.append(pending)
        pending = ""
    if pending:
        # A dangling shell continuation is malformed; fail closed.
        return True

    for line in logical_lines:
        stripped = line.strip()
        if not stripped.startswith("git add "):
            continue
        try:
            arguments = shlex.split(stripped)
        except ValueError:
            return True
        for value in arguments[2:]:
            if value == "--" or value.startswith("-"):
                continue
            normalized = value.replace("\\", "/")
            while normalized.startswith("./"):
                normalized = normalized[2:]
            if normalized == "data" or normalized.startswith("data/"):
                return True
    return False


def upload_step_block(lines: list[str], upload_index: int) -> tuple[int, str]:
    """Return the exact YAML list item containing an upload-artifact action."""
    step_pattern = re.compile(r"^(\s*)-\s+(?:name|uses):")
    step_start = next(
        (
            candidate
            for candidate in range(upload_index, -1, -1)
            if step_pattern.match(lines[candidate])
        ),
        None,
    )
    if step_start is None:
        raise ValueError("upload-artifact action is not inside a recognizable step")

    match = step_pattern.match(lines[step_start])
    assert match is not None
    step_indent = len(match.group(1))
    step_end = len(lines)
    for candidate in range(step_start + 1, len(lines)):
        line = lines[candidate]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent < step_indent or (
            indent == step_indent and re.match(r"^\s*-\s+", line)
        ):
            step_end = candidate
            break
    return step_start, "\n".join(lines[step_start:step_end])


def main() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "data"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.splitlines()
    if tracked != ["data/.gitkeep"]:
        raise SystemExit(
            "tracked data paths must be exactly ['data/.gitkeep'], "
            f"got: {tracked[:10]}"
        )
    errors: list[str] = []
    for workflow in (ROOT / ".github/workflows").glob("*.y*ml"):
        text = workflow.read_text(encoding="utf-8")
        if re.search(r"(?m)^\s*git\s+add\s+(?:-A|\.)\s*$", text):
            errors.append(f"{workflow.name}: broad git add is forbidden")
        if stages_data_directory(text):
            errors.append(f"{workflow.name}: runtime data directory must not be staged")
        lines = text.splitlines()
        upload_indexes = [
            index for index, line in enumerate(lines) if "uses: actions/upload-artifact@" in line
        ]
        for index in upload_indexes:
            try:
                step_start, block = upload_step_block(lines, index)
            except ValueError as exc:
                errors.append(f"{workflow.name}: {exc}")
                continue
            retention = re.search(r"retention-days:\s*(\d+)", block)
            artifact_name = re.search(r"(?m)^\s+name:\s*(.+)$", block)
            classification_text = lines[step_start] + " " + (
                artifact_name.group(1) if artifact_name else ""
            )
            diagnostic = "if: failure()" in block or bool(
                re.search(r"(?i)(error|failure|diagnostic)[-_ ]?(log|artifact)?", classification_text)
            )
            expected = 7 if diagnostic else 3
            if retention is None:
                errors.append(f"{workflow.name}: upload-artifact step lacks retention-days")
            elif int(retention.group(1)) != expected:
                errors.append(
                    f"{workflow.name}: {'diagnostic' if diagnostic else 'success'} artifact "
                    f"retention must be {expected}, got {retention.group(1)}"
                )
    if errors:
        raise SystemExit("\n".join(errors))
    print("storage policy valid")


if __name__ == "__main__":
    main()
