#!/usr/bin/env python3
"""Carry published phone identities forward into a newly merged candidate."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
import re
from typing import Any

from merge_phones import (
    clean_spec_value,
    derive_brand_from_name,
    model_key,
    normalize_audited_published_headers,
    normalize_brand,
    _strip_residue,
)
from verify_publish_superset import identity_key, identity_keys, is_below_min_publish_year, load_rows, verify_superset


def spu_config_key(row: dict[str, Any]) -> str:
    """SPU+配置 级身份键：model_key(品牌|型号剥离变体/后缀)|内存数字|存储数字。

    与 手机ID 身份互补：源数据 id 在输入间漂移（如 PCL git 恢复 409 行 vs 稳定
    artifact 541 行的 id 集合不同）时，同产品行仍能互相覆盖，让基线旧状态行
    能被新规则重算；不同配置（12GB vs 16GB）不会互相覆盖。
    型号部分复用 merge_phones.model_key（含品牌归一与容量变体/后缀剥离），
    避免跨品牌同型号碰撞（品牌A X10 vs 品牌B X10 键不同）。
    """
    mk = model_key(row)
    if not mk:
        model = str(row.get("型号") or row.get("name") or "").strip().lower()
        model = re.sub(r"\s+", "", model)
        mk = model
    brand = normalize_brand(row.get("品牌") or derive_brand_from_name(str(row.get("型号") or "")))
    if not brand:
        brand = str(row.get("品牌") or "").strip().casefold() or derive_brand_from_name(str(row.get("型号") or ""))
    # 容量数字只取 GB/TB 容量值（"16GB|LPDDR5" -> "16"），避免混入类型后缀数字
    # （LPDDR5 的 5、UFS 3.1 的 3）导致同产品不同源字段格式产生不同 spu 键。
    mem = "|".join(sorted(set(re.findall(r"(\d+)\s*[GT]B", str(row.get("内存") or ""), re.IGNORECASE))))
    sto = "|".join(sorted(set(re.findall(r"(\d+)\s*[GT]B", str(row.get("存储") or ""), re.IGNORECASE))))
    return f"spu:{brand}|{mk}|{mem}|{sto}"


def preserve_baseline(
    baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    covered_ids = set()
    for row in candidate:
        keys = identity_keys(row)
        if keys:
            covered_ids.add(keys[0])
    covered_ids.update(spu_config_key(row) for row in candidate)

    # pre-pass：spu 匹配的基线行 id 合并进 candidate 行关联手机ID——id 漂移行
    # （旧输入 id 不在当前候选）被 spu 覆盖替代时，旧 id 保留在关联手机ID，
    # 既让 verify_superset 的基线身份检查通过（traceability 不丢），
    # 又让新归并规则能重算这些行的验证状态。
    cand_spu_rows: dict[str, list[dict[str, Any]]] = {}
    for crow in candidate:
        cand_spu_rows.setdefault(spu_config_key(crow), []).append(crow)

    def _spu_replacement_ok(spu_key: str, row: dict[str, Any]) -> bool:
        """spu 覆盖时源数保护：候选匹配行源数 >= 基线行才替代。

        ZOL 数据缺失时 candidate 可能只有单源变体行（如 CNMO "Reno9 Pro(16+256GB)"），
        而基线有同 spu 的三源型号级行（ZOL+PCL+CNMO）——直接替代会丢掉 ZOL/PCL 信息
        （线上实测 92 个型号级行被误替代）。候选源数不足时保留基线行。
        """
        cand_rows = cand_spu_rows.get(spu_key, [])
        if not cand_rows:
            return True
        best = max(_source_count(c) for c in cand_rows)
        return best >= _source_count(row)

    baseline_spu_index: dict[str, list[dict[str, Any]]] = {}
    for brow in baseline:
        baseline_spu_index.setdefault(spu_config_key(brow), []).append(brow)
    for crow in candidate:
        for brow in baseline_spu_index.get(spu_config_key(crow), []):
            brow_keys = identity_keys(brow)
            if not brow_keys:
                continue
            bid = brow_keys[0]  # 只合并主 id——关联 id 是归并痕迹，不代表真实覆盖
            # 注意：不能把 bid 加进 covered_ids——否则主循环会把基线行主 id 判定为
            # "已覆盖"而替代（三源型号级行被单源变体替代，线上 92 型号丢失根因）。
            # traceability 靠关联手机ID 保留（verify_superset 检查 candidate 行 identity_keys）。
            if bid.startswith("id:"):
                related = str(crow.get("关联手机ID") or "")
                related_values = {v.strip() for v in re.split(r"[|,，\s]+", related) if v.strip()}
                related_values.add(bid[3:])
                crow["关联手机ID"] = "|".join(sorted(related_values))

    def source_count(row: dict[str, Any]) -> int:
        return len([part for part in str(row.get("数据来源", "")).split("+") if part.strip()])

    _source_count = source_count

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
        spu_key = spu_config_key(row)
        # 主 id 覆盖（candidate 有真实同 id 行）→ 替代。注意：不能用 all(keys)——
        # 关联手机ID 覆盖只是"归并痕迹"（变体行的关联含型号级行 id），不代表 candidate
        # 有同 id 行，用 all 会把三源型号级行误判为已覆盖而丢弃（线上 92 型号丢失根因）。
        primary = keys[0] if keys else ""
        if primary and primary in covered_ids:
            continue
        if spu_key in covered_ids:
            # 源数保护：候选行源数不足（ZOL 缺失时单源变体 vs 基线三源型号级）→
            # 保留基线行（信息更全），且不加 spu 到 covered（同 spu 其他基线行也保留）。
            if not _spu_replacement_ok(spu_key, row):
                selected.append((index, row))
                covered_ids.update(keys)
                continue
            continue
        selected.append((index, row))
        covered_ids.update(keys)
        # 注意：不能把保留行的 spu 键加入 covered——否则后续同 SPU+配置 的行
        # （candidate 同样没有）会被误判为已覆盖而不再保留，造成数据丢失。
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
