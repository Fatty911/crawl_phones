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

    for key in ("crawled_phones", "processed_phones", "crawled_pages"):
        values = [current.get(key), ours.get(key), theirs.get(key)]
        merged[key] = merge_unique_lists(*values)

    skipped: dict[str, Any] = {}
    for source in (theirs, ours, current):
        value = source.get("skipped_phones")
        if isinstance(value, dict):
            skipped.update(value)
    if skipped:
        merged["skipped_phones"] = skipped

    if "total_phones" in merged:
        merged["total_phones"] = max_number(
            current.get("total_phones"),
            ours.get("total_phones"),
            theirs.get("total_phones"),
            default=len(merged.get("crawled_phones", [])),
        )

    sources = [source for source in (current, ours, theirs) if source]
    is_pconline = any(
        "current_brand" in source or "brand_plan" in source for source in sources
    )
    if is_pconline:
        cursor_sources = [
            source
            for source in sources
            if isinstance(source.get("current_brand_index"), int)
            and isinstance(source.get("current_page"), int)
        ]
        if cursor_sources:
            plans = [source.get("brand_plan") for source in cursor_sources]
            plans_are_comparable = bool(plans) and all(
                isinstance(plan, list) and plan and plan == plans[0]
                for plan in plans
            )
            if len(cursor_sources) > 1 and not plans_are_comparable:
                merged["current_brand_index"] = 0
                merged["current_brand"] = ""
                merged["current_page"] = 1
                merged["previous_list_brand"] = ""
                merged["previous_list_page"] = 0
                merged["previous_list_ids"] = []
                merged["list_page_fingerprints"] = {}
            else:
                # A conflict must never synthesize a later page for another
                # brand. Replay the earliest complete cursor bundle.
                cursor_source = min(
                    cursor_sources,
                    key=lambda source: (
                        source["current_brand_index"],
                        source["current_page"],
                    ),
                )
                for key in (
                    "current_brand_index",
                    "current_brand",
                    "current_page",
                    "brand_plan",
                    "previous_list_brand",
                    "previous_list_page",
                    "previous_list_ids",
                    "list_page_fingerprints",
                ):
                    if key in cursor_source:
                        merged[key] = cursor_source[key]
        merged["scan_complete"] = bool(sources) and all(
            source.get("scan_complete") is True for source in sources
        )
    else:
        for key in ("current_page", "current_brand_index"):
            if key in merged:
                merged[key] = max_number(
                    current.get(key),
                    ours.get(key),
                    theirs.get(key),
                    default=1,
                )

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
