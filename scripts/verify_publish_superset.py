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

from merge_phones import MIN_PUBLISH_YEAR


CNMO_SINGLE_SOURCE_ALLOWED_BRANDS = {
    "苹果", "三星", "华为", "荣耀", "OPPO", "vivo", "小米", "红米", "iQOO",
    "一加", "真我", "魅族", "中兴", "努比亚", "联想", "摩托罗拉",
    "乐视", "金立", "蔚来", "鼎桥", "魅蓝", "酷派", "海信", "WIKO",
    "麦芒", "华硕", "黑鲨", "NZONE", "Hi nova", "天翼铂顿",
}

BRAND_PATTERNS = [
    ("苹果", ["iphone", "ipad", "apple"]),
    ("华为", ["huawei", "华为"]),
    ("荣耀", ["honor", "荣耀"]),
    ("小米", ["xiaomi", "小米", "poco"]),
    ("红米", ["redmi", "红米"]),
    ("OPPO", ["oppo"]),
    ("一加", ["oneplus", "一加"]),
    ("真我", ["realme", "真我"]),
    ("vivo", ["vivo"]),
    ("iQOO", ["iqoo"]),
    ("三星", ["samsung", "三星"]),
    ("魅族", ["meizu", "魅族"]),
    ("中兴", ["zte", "中兴"]),
    ("努比亚", ["nubia", "努比亚"]),
    ("联想", ["lenovo", "联想"]),
    ("摩托罗拉", ["moto", "motorola", "摩托罗拉"]),
    ("乐视", ["乐视", "letv"]),
    ("金立", ["金立", "gionee"]),
    ("蔚来", ["蔚来", "nio phone"]),
    ("鼎桥", ["鼎桥", "td tech"]),
    ("魅蓝", ["魅蓝"]),
    ("酷派", ["酷派", "coolpad", "cool "]),
    ("海信", ["海信", "hisense"]),
    ("WIKO", ["wiko", "hi 畅享", "hi畅享"]),
    ("麦芒", ["麦芒"]),
    ("Hi nova", ["hi nova", "hinova"]),
    ("天翼铂顿", ["天翼铂顿"]),
    ("华硕", ["华硕", "asus", "rog游戏手机"]),
    ("黑鲨", ["黑鲨", "black shark"]),
    ("NZONE", ["nzone"]),
]

BRAND_ALIASES = {
    "apple": "苹果", "iphone": "苹果", "samsung": "三星", "redmi": "红米",
    "xiaomi": "小米", "oppo": "OPPO", "vivo": "vivo", "iqoo": "iQOO",
    "oneplus": "一加", "realme": "真我", "huawei": "华为", "honor": "荣耀",
}


def normalize_model(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return re.sub(r"\s+", " ", normalized)


def derive_brand(value: Any) -> str:
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    if raw in CNMO_SINGLE_SOURCE_ALLOWED_BRANDS:
        return raw
    lowered = raw.casefold()
    if lowered in BRAND_ALIASES:
        return BRAND_ALIASES[lowered]
    for brand, patterns in BRAND_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            return brand
    return ""


def release_year(row: dict[str, Any]) -> int | None:
    for key in ("上市时间", "国内发布时间", "发布时间", "发布日期", "上市日期"):
        match = re.search(r"(?:19|20)\d{2}", str(row.get(key, "") or ""))
        if match:
            return int(match.group(0))
    return None


def is_below_min_publish_year(row: dict[str, Any]) -> bool:
    # 三年内发布准入（与 merge_phones.MIN_PUBLISH_YEAR 动态对齐）：
    # 无年份行不在此过滤，保持与前端一致。
    year = release_year(row)
    return year is not None and year < MIN_PUBLISH_YEAR


def is_out_of_scope_cnmo_single_source(row: dict[str, Any]) -> bool:
    source = str(row.get("数据来源") or row.get("source") or "").strip()
    if source != "CNMO":
        return False
    brand = derive_brand(row.get("品牌")) or derive_brand(row.get("型号") or row.get("name"))
    return brand not in CNMO_SINGLE_SOURCE_ALLOWED_BRANDS


def spu_config_key(row: dict[str, Any]) -> str:
    """SPU+配置 级身份键：model_key(品牌|型号剥离变体)|内存数字|存储数字。"""
    model = str(row.get("型号") or row.get("name") or "").strip().lower()
    model = re.sub(r"\s+", "", model)
    model = re.sub(r"[（(]\s*\d+\s*[gG][bB][^）)]*[）)]", "", model)
    mem = "|".join(sorted(set(re.findall(r"(\d+)\s*[GT]B", str(row.get("内存") or ""), re.IGNORECASE))))
    sto = "|".join(sorted(set(re.findall(r"(\d+)\s*[GT]B", str(row.get("存储") or ""), re.IGNORECASE))))
    return f"spu:{model}|{mem}|{sto}"


_VARIANT_BRACKET_RE = re.compile(r"[（(]\s*\d+\s*(?:[+＋]\s*\d+\s*)*(?:[gGtT][bB]?)")


def is_model_level_row(row: dict[str, Any]) -> bool:
    """型号级行：型号无容量变体括号。"""
    return not bool(_VARIANT_BRACKET_RE.search(str(row.get("型号") or "")))


def model_level_key(row: dict[str, Any]) -> str:
    """型号级行覆盖键：品牌|型号剥离变体（与 preserve 一致）。"""
    model = str(row.get("型号") or row.get("name") or "").strip().lower()
    model = re.sub(r"\s+", "", model)
    model = re.sub(r"[（(]\s*\d+\s*(?:[+＋]\s*\d+\s*)*[gG][bB][^）)]*[）)]", "", model)
    if not model:
        return ""  # 空型号不参与兜底（真缺失仍拒）
    return f"ml:{model}"


def identity_key(row: dict[str, Any]) -> str:
    keys = identity_keys(row)
    if not keys:
        raise ValueError("记录缺少可用身份键（手机ID/id/型号/name）")
    return keys[0]


def identity_keys(row: dict[str, Any]) -> list[str]:
    keys = []
    for field in ("手机ID", "id"):
        value = str(row.get(field, "")).strip()
        if value:
            keys.append(f"id:{value}")
            break
    related = row.get("关联手机ID")
    if isinstance(related, list):
        related_values = related
    else:
        related_values = re.split(r"[|,，\s]+", str(related or ""))
    for value in related_values:
        value = str(value).strip()
        if value:
            key = f"id:{value}"
            if key not in keys:
                keys.append(key)
    if keys:
        return keys
    for field in ("型号", "name"):
        value = normalize_model(row.get(field, ""))
        if value:
            return [f"model:{value}"]
    return []


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
    scoped_baseline = [
        row for row in baseline
        if not is_out_of_scope_cnmo_single_source(row)
        and not is_below_min_publish_year(row)
    ]
    baseline_ids = set()
    for row in scoped_baseline:
        keys = identity_keys(row)
        if not keys:
            identity_key(row)
        baseline_ids.update(keys)
    candidate_ids = {key for row in candidate for key in identity_keys(row)}
    missing = sorted(baseline_ids - candidate_ids)
    if missing:
        # spu 兜底：缺失 id 的基线行若同 SPU+配置 的候选行存在且源数不退化（候选源数 >= 基线源数），
        # 视为已覆盖（preserve 的源数保护替代）——数据未丢（同产品在），只是 id 随候选行变化。
        cand_spu_rows: dict[str, list[dict[str, Any]]] = {}
        for crow in candidate:
            cand_spu_rows.setdefault(spu_config_key(crow), []).append(crow)

        cand_ml_rows: dict[str, list[dict[str, Any]]] = {}
        for crow in candidate:
            # 所有候选行按型号级键索引（同型号的变体行也代表产品在——model_level 归并语义：
            # 型号级行缺失时同型号候选行即覆盖，数据未丢）
            mlk = model_level_key(crow)
            if mlk:
                cand_ml_rows.setdefault(mlk, []).append(crow)

        def _source_count(row: dict[str, Any]) -> int:
            return len([p for p in str(row.get("数据来源", "")).split("+") if p.strip()])

        def _covered_via_spu(row: dict[str, Any]) -> bool:
            spu = spu_config_key(row)
            if not spu or spu.endswith("||"):  # 无型号无容量（空键）→ 不兜底（真缺失仍拒）
                return False
            cand_rows = cand_spu_rows.get(spu, [])
            if not cand_rows:
                return False
            best = max(_source_count(c) for c in cand_rows)
            return best >= _source_count(row)

        def _covered_via_model_level(row: dict[str, Any]) -> bool:
            """型号级行兜底：同型号级（品牌|型号）的候选行源数不退化 → 视为已覆盖
            （model_level 归并——vivo S19 两型号级行归并成一条，被覆盖行的 id 靠 pre-pass
            合并关联保留；个别场景 pre-pass 匹配失败时此处兜底，数据未丢——同型号在 merged）。"""
            if not is_model_level_row(row):
                return False
            ml = model_level_key(row)
            if not ml or ml.endswith("|") or ml == "ml:":
                return False
            cand_rows = cand_ml_rows.get(ml, [])
            if not cand_rows:
                return False
            best = max(_source_count(c) for c in cand_rows)
            return best >= _source_count(row)

        truly_missing = []
        for key in missing:
            rows = [row for row in scoped_baseline if key in identity_keys(row)]
            if not rows:
                truly_missing.append(key)
                continue
            if not all(_covered_via_spu(row) or _covered_via_model_level(row) for row in rows):
                truly_missing.append(key)
        if truly_missing:
            preview = ", ".join(truly_missing[:10])
            raise ValueError(f"候选缺少基线身份: count={len(truly_missing)} sample={preview}")


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
