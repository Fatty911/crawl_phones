#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 ZOL 搜索补充的型号列表：线上 2024+ 机型（SPU 去重，按单源优先排序）。"""
import json
import re
import sys
import time
import urllib.request

URL = "https://phones.jiucai.eu.org/data/latest.json"

# 极冷门/山寨品牌不搜（发布层已过滤，搜索浪费额度）
SHANZHAI_BRANDS = {
    "乐视", "金立", "水月雨", "Polestar", "蔚来", "Oukitel",
}
OUT = "/tmp/zol_models.txt"
YEAR_RE = re.compile(r"(19|20)\d{2}")
from merge_phones import MIN_PUBLISH_YEAR
SPU_RE = re.compile(r"[（(].*?[)）]")


def main() -> int:
    try:
        req = urllib.request.Request(URL + "?t=" + str(int(time.time())))
        rows = json.load(urllib.request.urlopen(req, timeout=120))
    except Exception as e:
        print(f"下载线上数据失败: {e}", file=sys.stderr)
        # 失败时仍生成空文件（workflow 守卫 + 下游脚本双保险，避免 FileNotFoundError）
        open(OUT, "w", encoding="utf-8").close()
        return 0
    seen = set()
    spus = []
    # 单源优先（提升空间最大），再双源（三源机会）
    for r in sorted(rows, key=lambda x: (len(str(x.get("数据来源") or "").split("+")))):
        t = str(r.get("型号") or "").strip()
        if not t:
            continue
        raw = " ".join(str(x) for x in (r.get("品牌"), t, r.get("name")) if x).lower()
        if any(b.lower() in raw for b in SHANZHAI_BRANDS):
            continue
        m = YEAR_RE.search(str(r.get("上市时间") or ""))
        if m and int(m.group(0)) < MIN_PUBLISH_YEAR:
            continue
        spu = SPU_RE.sub("", t).strip()
        if spu and spu not in seen:
            seen.add(spu)
            spus.append(spu)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(spus))
    print(f"型号列表: {len(spus)} 个 -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
