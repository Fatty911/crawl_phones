#!/usr/bin/env python3
"""Validate raw CNMO output while mapping source fields to merge key fields."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


FIELD_ALIASES = {
    "处理器": ("处理器",),
    "内存": ("内存",),
    "存储": ("存储",),
    "屏幕": ("屏幕",),
    "电池": ("电池", "电池类型"),
    "摄像头参数": ("摄像头参数", "后置相机"),
    "上市时间": ("上市时间", "launch_time"),
}
MODEL_ALIASES = ("型号", "name")
MISSING_VALUES = {"", "-", "--", "/", "n/a", "null", "暂无", "无", "未知"}
MIN_VALID_RATE = 70
DEBUG_MIN_ROWS = 20
DEBUG_MAX_ROWS = 30


def has_value(value: Any) -> bool:
    if value is None:
        return False
    return str(value).strip().casefold() not in MISSING_VALUES


def has_any_alias(row: dict[str, Any], aliases: tuple[str, ...]) -> bool:
    return any(has_value(row.get(alias)) for alias in aliases)


def dataset_quality(rows: Any) -> dict[str, Any]:
    if not isinstance(rows, list):
        return {"row_count": 0, "model_count": 0, "field_counts": {}, "valid_rate": 0}

    objects = [row for row in rows if isinstance(row, dict)]
    field_counts = {
        field: sum(has_any_alias(row, aliases) for row in objects)
        for field, aliases in FIELD_ALIASES.items()
    }
    row_count = len(rows)
    model_count = sum(has_any_alias(row, MODEL_ALIASES) for row in objects)
    valid_rate = int(min(field_counts.values()) / row_count * 100) if row_count else 0
    return {
        "row_count": row_count,
        "model_count": model_count,
        "field_counts": field_counts,
        "valid_rate": valid_rate,
    }


def is_valid_dataset(rows: Any, *, debug: bool = False) -> bool:
    report = dataset_quality(rows)
    row_count = report["row_count"]
    if row_count < 1 or report["model_count"] != row_count:
        return False
    if debug and not DEBUG_MIN_ROWS <= row_count <= DEBUG_MAX_ROWS:
        return False
    return report["valid_rate"] >= MIN_VALID_RATE


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    try:
        rows = json.loads(args.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    report = dataset_quality(rows)
    valid = is_valid_dataset(rows, debug=args.debug)
    print(json.dumps({"valid": valid, **report}, ensure_ascii=False, sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
