#!/usr/bin/env python3
"""Fail closed unless a candidate phone dataset preserves the published baseline."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any


def normalize_model(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return re.sub(r"\s+", " ", normalized)


def identity_key(row: dict[str, Any]) -> str:
    for field in ("手机ID", "id"):
        value = str(row.get(field, "")).strip()
        if value:
            return f"id:{value}"
    for field in ("型号", "name"):
        value = normalize_model(row.get(field, ""))
        if value:
            return f"model:{value}"
    raise ValueError("记录缺少可用身份键（手机ID/id/型号/name）")


def load_rows(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取有效 JSON {path}: {exc}") from exc
    if not isinstance(payload, list):
        raise ValueError(f"JSON 顶层必须是数组: {path}")
    if not all(isinstance(row, dict) for row in payload):
        raise ValueError(f"JSON 数组只能包含对象: {path}")
    return payload


def verify_superset(
    baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]
) -> None:
    if len(candidate) < len(baseline):
        raise ValueError(f"候选行数减少: baseline={len(baseline)} candidate={len(candidate)}")
    baseline_ids = {identity_key(row) for row in baseline}
    candidate_ids = {identity_key(row) for row in candidate}
    missing = sorted(baseline_ids - candidate_ids)
    if missing:
        preview = ", ".join(missing[:10])
        raise ValueError(f"候选缺少基线身份: count={len(missing)} sample={preview}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    try:
        baseline = load_rows(args.baseline)
        candidate = load_rows(args.candidate)
        verify_superset(baseline, candidate)
    except ValueError as exc:
        print(f"发布超集校验失败: {exc}", file=sys.stderr)
        return 1
    print(f"发布超集校验通过: baseline={len(baseline)} candidate={len(candidate)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
