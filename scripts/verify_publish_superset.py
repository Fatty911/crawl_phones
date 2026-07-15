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


def is_out_of_scope_cnmo_single_source(row: dict[str, Any]) -> bool:
    source = str(row.get("数据来源") or row.get("source") or "").strip()
    if source != "CNMO":
        return False
    brand = derive_brand(row.get("品牌")) or derive_brand(row.get("型号") or row.get("name"))
    return brand not in CNMO_SINGLE_SOURCE_ALLOWED_BRANDS


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
    scoped_baseline = [row for row in baseline if not is_out_of_scope_cnmo_single_source(row)]
    if len(candidate) < len(scoped_baseline):
        raise ValueError(f"候选行数减少: baseline={len(scoped_baseline)} candidate={len(candidate)}")
    baseline_ids = {identity_key(row) for row in scoped_baseline}
    candidate_ids = {key for row in candidate for key in identity_keys(row)}
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
