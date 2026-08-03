#!/usr/bin/env python3
"""Create a deterministic, machine-readable phone merge evidence report."""

from __future__ import annotations

import argparse
import csv
import glob
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def load_payload(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = next(
            (payload[key] for key in ("items", "data", "records") if isinstance(payload.get(key), list)),
            [],
        )
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def expand_inputs(patterns: list[str]) -> list[Path]:
    paths: dict[str, Path] = {}
    for pattern in patterns:
        matches = glob.glob(pattern)
        for match in matches:
            path = Path(match)
            if path.is_file():
                paths[path.as_posix()] = path
    return [paths[key] for key in sorted(paths)]


def source_names(row: dict[str, Any]) -> tuple[str, ...]:
    value = row.get("atomic_source_names")
    if isinstance(value, list):
        values = value
    else:
        values = re.split(r"[+,/|]", str(value or row.get("数据来源") or row.get("source") or ""))
    return tuple(sorted({str(item).strip() for item in values if str(item).strip()}))


def validation_status(row: dict[str, Any]) -> str:
    value = row.get("验证状态") or row.get("validation_status")
    if value:
        return str(value).strip()
    if "publish_eligible" in row:
        return "eligible" if row.get("publish_eligible") is True else "ineligible"
    return "unknown"


def summarize_raw(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    sources = Counter(name for row in rows for name in source_names(row))
    statuses = Counter(validation_status(row) for row in rows)
    return {
        "path": path.as_posix(),
        "row_count": len(rows),
        "source_counts": dict(sorted(sources.items())),
        "validation_status_counts": dict(sorted(statuses.items())),
        "multi_source_count": sum(len(source_names(row)) >= 2 for row in rows),
    }


def diff_row_count(path: Path | None) -> int:
    if path is None or not path.is_file():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def build_report(
    raw_paths: list[Path],
    merged_path: Path,
    diff_path: Path | None = None,
) -> dict[str, Any]:
    raw_reports = [summarize_raw(path, rows_from_payload(load_payload(path))) for path in raw_paths]
    merged_rows = rows_from_payload(load_payload(merged_path))
    combinations = Counter("+".join(source_names(row)) or "unknown" for row in merged_rows)
    statuses = Counter(validation_status(row) for row in merged_rows)
    return {
        "schema_version": "merge-evidence-v1",
        "raw": raw_reports,
        "published_count": len(merged_rows),
        "multi_source_count": sum(len(source_names(row)) >= 2 for row in merged_rows),
        "source_combinations": dict(sorted(combinations.items())),
        "validation_status_counts": dict(sorted(statuses.items())),
        "diff_row_count": diff_row_count(diff_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", nargs="+", required=True)
    parser.add_argument("--merged", required=True)
    parser.add_argument("--diff")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    raw_paths = expand_inputs(args.raw)
    if not raw_paths:
        raise SystemExit("no raw phone source files matched")
    merged_path = Path(args.merged)
    if not merged_path.is_file():
        raise SystemExit(f"merged phone file does not exist: {merged_path}")
    diff_path = Path(args.diff) if args.diff else None
    report = build_report(raw_paths, merged_path, diff_path)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
