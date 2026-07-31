#!/usr/bin/env python3
"""Analyze single-source data in a Pages payload.

Produces a JSON report with:
- total/multi/single counts and rates
- source distribution
- root cause categories (series-only-single, trim-merge-gap, source-coverage-gap)
- top single-source series/products
- actionable recommendations

Usage:
    python3 scripts/analyze_single_source.py --data ./data/latest.json --output ./audit_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def _detect_source_field(rows: list[dict]) -> str:
    """Detect which field holds the source label."""
    candidates = ("数据来源", "source", "来源", "atomic_source_names")
    for field in candidates:
        if rows and any(field in r for r in rows[:5]):
            return field
    return "数据来源"


def _source_count(value: str) -> int:
    """Count distinct sources from a source string like '懂车帝+汽车之家'."""
    if not value:
        return 0
    if "+" in value:
        return value.count("+") + 1
    if "仅" in value:
        return 1
    if "," in value:
        return value.count(",") + 1
    return 1 if value.strip() else 0


def analyze_cars(rows: list[dict], src_field: str) -> dict:
    """Car-specific analysis (by 车系/车系ID)."""
    by_series: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        series = str(r.get("车系", "") or r.get("车型", "") or "")
        sid = str(r.get("车系ID", "") or "")
        by_series[(series, sid)].append(r)

    series_sources: dict[tuple[str, str], set[str]] = {}
    for (series, sid), rs in by_series.items():
        srcs: set[str] = set()
        for r in rs:
            s = str(r.get(src_field, ""))
            if "懂车帝" in s or "DCD" in s:
                srcs.add("DCD")
            if "汽车之家" in s or "AH" in s:
                srcs.add("AH")
            if "易车" in s or "YC" in s:
                srcs.add("YC")
        series_sources[(series, sid)] = srcs

    single_series_rows = 0
    multi_series_single_rows = 0
    for (series, sid), srcs in series_sources.items():
        rs = by_series[(series, sid)]
        if len(srcs) <= 1:
            single_series_rows += len(rs)
        else:
            for r in rs:
                if _source_count(str(r.get(src_field, ""))) <= 1:
                    multi_series_single_rows += 1

    top_single_series = []
    for (series, sid), srcs in sorted(series_sources.items()):
        if len(srcs) <= 1:
            rs = by_series[(series, sid)]
            src_name = next(iter(srcs), "?")
            top_single_series.append(
                {"series": series, "id": sid, "source": src_name, "rows": len(rs)}
            )
    top_single_series.sort(key=lambda x: -x["rows"])
    return {
        "single_series_rows": single_series_rows,
        "multi_series_single_rows": multi_series_single_rows,
        "total_series": len(series_sources),
        "single_source_series": sum(1 for v in series_sources.values() if len(v) <= 1),
        "multi_source_series": sum(1 for v in series_sources.values() if len(v) > 1),
        "top_single_series": top_single_series[:30],
    }


def analyze_generic(rows: list[dict], src_field: str) -> dict:
    """Generic analysis for phones/laptops (by 品牌/型号 or brand/model)."""
    by_product: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        brand = str(r.get("品牌", "") or r.get("brand", "") or "")
        model = str(r.get("型号", "") or r.get("model", "") or r.get("title", "") or "")
        key = f"{brand} {model}".strip()
        by_product[key].append(r)

    single_source_products = 0
    multi_source_products = 0
    for key, rs in by_product.items():
        srcs = set()
        for r in rs:
            s = str(r.get(src_field, ""))
            srcs.add(s)
        if len(srcs) <= 1:
            single_source_products += 1
        else:
            multi_source_products += 1

    top_single = []
    for key, rs in by_product.items():
        srcs = set(str(r.get(src_field, "")) for r in rs)
        if len(srcs) <= 1:
            top_single.append(
                {"product": key, "source": list(srcs), "rows": len(rs)}
            )
    top_single.sort(key=lambda x: -x["rows"])
    return {
        "single_source_products": single_source_products,
        "multi_source_products": multi_source_products,
        "top_single_products": top_single[:30],
    }


def analyze(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        # crawl_laptops format
        rows = data["items"]
        src_field = "source"
    elif isinstance(data, dict) and "data" in data:
        rows = data["data"]
        src_field = _detect_source_field(rows)
    elif isinstance(data, list):
        rows = data
        src_field = _detect_source_field(rows)
    else:
        rows = []
        src_field = "数据来源"

    total = len(rows)
    src_dist: Counter[str] = Counter()
    multi_count = 0
    single_count = 0
    for r in rows:
        srcs = str(r.get(src_field, "") or "")
        n = _source_count(srcs)
        src_dist[srcs] += 1
        if n >= 2:
            multi_count += 1
        else:
            single_count += 1

    multi_rate = round(multi_count / total * 100, 2) if total else 0
    single_rate = round(single_count / total * 100, 2) if total else 0

    # Detect repo type
    is_cars = any("车系" in r for r in rows[:3]) if rows else False
    detail = analyze_cars(rows, src_field) if is_cars else analyze_generic(rows, src_field)

    causes = {
        "series_only_single": detail.get("single_series_rows", detail.get("single_source_products", 0)),
        "trim_merge_gap": detail.get("multi_series_single_rows", 0),
    }

    return {
        "total": total,
        "multi_count": multi_count,
        "single_count": single_count,
        "multi_rate": multi_rate,
        "single_rate": single_rate,
        "source_distribution": dict(src_dist.most_common(20)),
        "causes": causes,
        "detail": detail,
    }


def main():
    parser = argparse.ArgumentParser(description="Analyze single-source data")
    parser.add_argument("--data", required=True, help="Path to latest.json")
    parser.add_argument("--output", required=True, help="Output report JSON path")
    args = parser.parse_args()

    report = analyze(Path(args.data))
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Total: {report['total']}, Multi: {report['multi_count']} ({report['multi_rate']}%), Single: {report['single_count']} ({report['single_rate']}%)")
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
