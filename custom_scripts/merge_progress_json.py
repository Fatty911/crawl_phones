#!/usr/bin/env python3
"""Merge crawler progress JSON files after a rebase conflict."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def merge_unique_lists(*values: Any) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, list):
            continue
        for item in value:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key)
                merged.append(item)
    return merged


def max_number(*values: Any, default: int = 0) -> int:
    numbers = [value for value in values if isinstance(value, int)]
    return max(numbers) if numbers else default


def merge_progress(current: dict[str, Any], ours: dict[str, Any], theirs: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in (theirs, ours, current):
        merged.update(source)

    for key in ("crawled_phones", "crawled_pages"):
        values = [current.get(key), ours.get(key), theirs.get(key)]
        merged[key] = merge_unique_lists(*values)

    if "total_phones" in merged:
        merged["total_phones"] = max_number(
            current.get("total_phones"),
            ours.get("total_phones"),
            theirs.get("total_phones"),
            default=len(merged.get("crawled_phones", [])),
        )

    for key in ("current_page", "current_brand_index"):
        if key in merged:
            merged[key] = max_number(current.get(key), ours.get(key), theirs.get(key), default=1)

    return merged


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: merge_progress_json.py <output> <ours> <theirs>", file=sys.stderr)
        return 2

    output = Path(sys.argv[1])
    current = load_json(output)
    ours = load_json(Path(sys.argv[2]))
    theirs = load_json(Path(sys.argv[3]))

    merged = merge_progress(current, ours, theirs)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
