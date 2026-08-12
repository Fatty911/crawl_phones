#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PCL 站内搜索补充爬虫：按型号搜 ks.pconline，爬详情补 raw（覆盖列表页未收录的主流型号）。

用法：
  python pcl_search_supplement.py --models-file models.txt [--max-per-model 3] [--limit N]

输出写到 crawl_state/pconline/json/{id}.json（与 crawl_pconline step1 同格式，step2 自动合并）。
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# crawl_pconline 在模块级执行 argparse，import 前先屏蔽本脚本参数
_SAVED_ARGV = list(sys.argv)
sys.argv = ["crawl_pconline"]
from crawl_pconline import (  # noqa: E402
    normalize_phone_fields, derive_brand_from_name, extract_release_year,
    get_session, pconline_json_dir,
)
sys.argv = _SAVED_ARGV
from merge_phones import MIN_PUBLISH_YEAR  # noqa: E402

SEARCH_URL = "http://ks.pconline.com.cn/product.shtml"
RESULT_RE = re.compile(r"product\.pconline\.com\.cn/mobile/([a-z0-9]+)/(\d+)\.html", re.I)
REQUEST_TIMEOUT = 30
SEARCH_DELAY = 2.0
DETAIL_DELAY = 2.0


def fast_crawl_detail(session, phone_id: str, brand: str = "") -> Optional[dict]:
    """crawl_detail_page 的快速版（2s 间隔，批量搜索补充用）。"""
    if brand:
        url = f"https://product.pconline.com.cn/mobile/{brand}/{phone_id}.html"
    else:
        url = f"https://product.pconline.com.cn/mobile/{phone_id}.html"
    try:
        time.sleep(DETAIL_DELAY)
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.encoding = "gbk"
        if resp.status_code != 200:
            return None
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        detail = {"phone_id": phone_id, "url": url,
                  "crawl_time": datetime.now().isoformat()}
        title = soup.find("h1")
        if title:
            detail["name"] = title.get_text(strip=True)
        info_div = soup.find("div", class_="info")
        if info_div:
            for item in info_div.find_all("li"):
                text = item.get_text(strip=True)
                if "：" in text:
                    key, value = text.split("：", 1)
                    if key and value:
                        detail[key.strip()] = value.strip()
        return detail
    except Exception:
        return None


def search_models(session, model: str, max_ids: int) -> list:
    """搜索型号，返回 (brand, id) 列表（去重，按出现顺序）。"""
    try:
        time.sleep(SEARCH_DELAY)
        resp = session.get(SEARCH_URL, params={"q": model}, timeout=REQUEST_TIMEOUT,
                           headers={"Referer": "http://ks.pconline.com.cn/"})
        resp.encoding = "gbk"
        if resp.status_code != 200:
            return []
        seen = set()
        out = []
        for m in RESULT_RE.finditer(resp.text):
            key = (m.group(1), m.group(2))
            if key not in seen:
                seen.add(key)
                out.append(key)
            if len(out) >= max_ids:
                break
        return out
    except Exception:
        return []


def crawl_one(session, brand: str, phone_id: str) -> bool:
    """爬详情，标准化后写入 pconline_json_dir。返回是否成功。"""
    out = os.path.join(pconline_json_dir, f"{phone_id}.json")
    if os.path.exists(out):
        return False
    detail = fast_crawl_detail(session, phone_id, brand)
    if not detail:
        return False
    phone = dict(detail)
    phone["id"] = phone_id
    year = extract_release_year(phone)
    if year is not None and year < MIN_PUBLISH_YEAR:
        return False
    phone = normalize_phone_fields(phone)
    if not phone.get("品牌"):
        phone["品牌"] = derive_brand_from_name(phone.get("型号", phone.get("name", "")))
    phone["source_supplement"] = "pcl_search"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(phone, f, ensure_ascii=False, indent=2)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-file", required=True)
    parser.add_argument("--max-per-model", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    models = []
    with open(args.models_file, encoding="utf-8") as f:
        for line in f:
            m = line.strip()
            if m:
                models.append(m)
    if args.limit:
        models = models[: args.limit]
    print(f"型号数: {len(models)}", flush=True)

    session = get_session()
    total_new = 0
    total_hit = 0
    for i, model in enumerate(models, 1):
        hits = search_models(session, model, args.max_per_model)
        if hits:
            total_hit += 1
        added = 0
        for brand, pid in hits:
            if crawl_one(session, brand, pid):
                added += 1
        total_new += added
        print(f"[{i}/{len(models)}] {model}: 命中 {len(hits)}, 新增 {added}", flush=True)
        if i % 20 == 0:
            print(f"  进度: 命中 {total_hit}/{i}, 新增 {total_new}", flush=True)
    print(f"完成: 型号 {len(models)}, 命中 {total_hit}, 新增详情 {total_new}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
