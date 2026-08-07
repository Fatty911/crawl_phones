#!/usr/bin/env python3
"""Carry published phone identities forward into a newly merged candidate."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from merge_phones import clean_spec_value, normalize_audited_published_headers, _strip_residue
from verify_publish_superset import identity_key, identity_keys, is_below_min_publish_year, load_rows, verify_superset


def preserve_baseline(
    baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    covered_ids = {key for row in candidate for key in identity_keys(row)}

    def source_count(row: dict[str, Any]) -> int:
        return len([part for part in str(row.get("数据来源", "")).split("+") if part.strip()])

    # 五年内准入：旧年份行（<2022）不再向后保留（与 merge 的 MIN_PUBLISH_YEAR 对齐）
    baseline = [row for row in baseline if not is_below_min_publish_year(row)]

    ranked_baseline = sorted(
        enumerate(baseline),
        key=lambda item: (-source_count(item[1]), -len(identity_keys(item[1])), item[0]),
    )
    selected: list[tuple[int, dict[str, Any]]] = []
    for index, row in ranked_baseline:
        keys = identity_keys(row)
        if not keys:
            identity_key(row)
        if any(key not in covered_ids for key in keys):
            selected.append((index, row))
            covered_ids.update(keys)
    missing_rows = [row for _, row in sorted(selected, key=lambda item: item[0])]
    merged = [
        normalize_audited_published_headers(row)
        for row in [*candidate, *(dict(row) for row in missing_rows)]
    ]
    for row in merged:
        for field in ("内存", "存储"):
            if field in row:
                row[field] = clean_spec_value(field, row[field])
        # 存量行差异文本也做源站残留清洗（差异文本曾用原始值输出，残留残留页面）
        if "交叉验证差异" in row and row["交叉验证差异"] not in (None, "-"):
            row["交叉验证差异"] = _strip_residue(str(row["交叉验证差异"]))
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
