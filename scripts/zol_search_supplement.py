#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZOL 站内搜索补充爬虫：按型号搜索 ZOL 站内，爬详情补 raw（绕过列表页 checking 墙）。

用法：
  python zol_search_supplement.py --models-file models.txt [--max-per-model 5] [--limit N]

models.txt 每行一个型号（SPU 名，如 "vivo X100" / "红米K60"）。
输出写到 crawl_state/zol/json/{id}.json（与 crawl_zol step1 同格式，step2 自动合并）。
"""
import argparse
import json
import os
import re
import sys
import time
from typing import Optional
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# crawl_zol 在模块级执行 argparse（parse_args），import 前先屏蔽本脚本参数
_SAVED_ARGV = list(sys.argv)
sys.argv = ["crawl_zol"]
from crawl_zol import (  # noqa: E402
    BASE_URL, normalize_phone_fields, derive_brand_from_name,
    extract_release_year, get_session, zol_json_dir,
)
sys.argv = _SAVED_ARGV
from merge_phones import MIN_PUBLISH_YEAR  # noqa: E402

SEARCH_URL = "https://search.zol.com.cn/s/all.php"
ID_RE = re.compile(r"cell_phone/index(\d+)\.shtml")
REQUEST_TIMEOUT = 30
SEARCH_DELAY = 3.0   # 搜索间隔（秒）——批量场景，比人工模拟快
DETAIL_DELAY = 2.0   # 详情间隔（秒）——详情页无 checking 墙，200 快速返回


def fast_crawl_detail(session, phone_id: str) -> Optional[dict]:
    """crawl_detail_page 的快速版（2s 间隔，批量搜索补充用）。"""
    url = f"{BASE_URL}/cell_phone/index{phone_id}.shtml"
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
        labels = soup.find_all("label")
        for label in labels:
            label_text = label.get_text(strip=True)
            nxt = label.find_next_sibling()
            if nxt:
                value = nxt.get_text(strip=True)
                if label_text and value:
                    key = label_text.rstrip("：:").strip()
                    if key:
                        detail[key] = value
        return detail
    except Exception:
        return None


def fast_crawl_param(session, phone_id: str, category_id: str = "2140") -> Optional[dict]:
    """crawl_param_page 的快速版。"""
    url = f"{BASE_URL}/{category_id}/{phone_id}/param.shtml"
    try:
        time.sleep(DETAIL_DELAY)
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.encoding = "gbk"
        if resp.status_code != 200:
            return None
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        params = {}
        for li in soup.find_all("li"):
            name = li.find("span", class_=re.compile("name|left"))
            val = li.find("span", class_=re.compile("value|right"))
            if name and val:
                k = name.get_text(strip=True).rstrip("：:").strip()
                v = val.get_text(strip=True)
                if k and v:
                    params[k] = v
        return params
    except Exception:
        return None


def search_ids(session, model: str, max_ids: int) -> list:
    """搜索型号，返回详情 ID 列表（按搜索页出现顺序去重）。"""
    try:
        time.sleep(SEARCH_DELAY)
        resp = session.get(SEARCH_URL, params={"kword": model}, timeout=30)
        resp.encoding = resp.apparent_encoding or "gbk"
        if resp.status_code != 200:
            print(f"  搜索失败 {model}: HTTP {resp.status_code}", flush=True)
            return []
        ids = []
        for m in ID_RE.finditer(resp.text):
            pid = m.group(1)
            if pid not in ids:
                ids.append(pid)
            if len(ids) >= max_ids:
                break
        return ids
    except Exception as e:
        print(f"  搜索异常 {model}: {e}", flush=True)
        return []


def crawl_one(session, phone_id: str) -> bool:
    """爬详情+参数，标准化后写入 zol_json_dir。返回是否成功。"""
    out = os.path.join(zol_json_dir, f"{phone_id}.json")
    if os.path.exists(out):
        return False  # 已爬过
    detail = fast_crawl_detail(session, phone_id)
    if not detail:
        return False
    phone = dict(detail)
    phone["id"] = phone_id
    year = extract_release_year(phone)
    if not year:
        params = fast_crawl_param(session, phone_id)
        if params:
            phone.update(params)
            year = extract_release_year(phone)
    if year is not None and year < MIN_PUBLISH_YEAR:
        return False  # 三年内准入（与 merge 对齐）
    if "处理器" not in phone:
        params = fast_crawl_param(session, phone_id)
        if params:
            phone.update(params)
    phone = normalize_phone_fields(phone)
    if not phone.get("品牌"):
        phone["品牌"] = derive_brand_from_name(phone.get("型号", phone.get("name", "")))
    phone["source_supplement"] = "zol_search"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(phone, f, ensure_ascii=False, indent=2)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-file", required=True)
    parser.add_argument("--max-per-model", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0, help="最多处理型号数（0=全部）")
    args = parser.parse_args()

    models = []
    with open(args.models_file, encoding="utf-8") as f:
        for line in f:
            m = line.strip()
            if m:
                models.append(m)
    if args.limit:
        models = models[: args.limit]
    print(f"型号数: {len(models)}（max_per_model={args.max_per_model}）", flush=True)

    session = get_session()
    total_new = 0
    total_hit = 0
    for i, model in enumerate(models, 1):
        ids = search_ids(session, model, args.max_per_model)
        if ids:
            total_hit += 1
        added = 0
        for pid in ids:
            if crawl_one(session, pid):
                added += 1
        total_new += added
        print(f"[{i}/{len(models)}] {model}: 搜索到 {len(ids)} 个, 新增 {added}", flush=True)
        if i % 20 == 0:
            print(f"  进度: 命中 {total_hit}/{i}, 新增 {total_new}", flush=True)

    print(f"完成: 型号 {len(models)}, 命中 {total_hit}, 新增详情 {total_new}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
