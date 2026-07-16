#!/usr/bin/env python3
"""Carry published phone identities forward into a newly merged candidate."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from verify_publish_superset import identity_key, identity_keys, load_rows, verify_superset


def preserve_baseline(
    baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    candidate_ids = {key for row in candidate for key in identity_keys(row)}
    missing_rows = [row for row in baseline if identity_key(row) not in candidate_ids]
    merged = [*candidate, *(dict(row) for row in missing_rows)]
    return merged, [identity_key(row) for row in missing_rows]


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate_json", type=Path)
    parser.add_argument("candidate_csv", type=Path)
    args = parser.parse_args()

    try:
        baseline = load_rows(args.baseline)
        candidate = load_rows(args.candidate_json)
        merged, missing = preserve_baseline(baseline, candidate)
        if missing:
            write_json(args.candidate_json, merged)
            write_csv(args.candidate_csv, merged)
        verify_superset(baseline, merged)
    except (OSError, ValueError) as exc:
        print(f"保留线上基线失败: {exc}", file=sys.stderr)
        return 1

    preview = ", ".join(missing[:10]) if missing else "-"
    print(
        f"线上基线身份已保留: baseline={len(baseline)} candidate={len(merged)} "
        f"restored={len(missing)} sample={preview}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
