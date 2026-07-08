#!/usr/bin/env python3
"""
CNMO（手机中国）爬虫 - 爬取全部手机型号的配置信息
https://product.cnmo.com/all/product_t1_p{page}.html

列表页：服务端渲染 HTML，GBK 编码，每页约 32 款
详情页：https://product.cnmo.com/cell_phone/index{id}.shtml
总产品数：约 15,648 款，165 页
"""

import os
import sys
import json
import re
import time
import random
import argparse
import logging
from datetime import datetime, date
from typing import List, Dict, Optional
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

import requests
from bs4 import BeautifulSoup

# ===== 配置 =====
BASE_URL = "https://product.cnmo.com"
LIST_URL = f"{BASE_URL}/all/product_t1_p{{page}}.html"
DETAIL_URL = f"{BASE_URL}/cell_phone/index{{pid}}.shtml"
REQUEST_TIMEOUT = 30
MIN_DELAY = 1.0
MAX_DELAY = 3.0
MAX_RETRIES = 3
PROGRESS_FILE = "crawl_state/cnmo_progress.json"

# 日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cnmo")

# 工作目录
working_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
data_dir = os.path.join(working_dir, "data")
os.makedirs(data_dir, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://product.cnmo.com/all/product.html",
}

# 详情页字段提取规则
DETAIL_FIELDS = {
    "上市时间": r"上市时间[：:]\s*(\S+)",
    "参考报价": r"参考[报报]价[：:]\s*(\S+)",
    "电商报价": r"电商[报报]价[：:]\s*(\S+)",
    "基本参数": None,  # 特殊处理
}

# 参数表格字段映射
PARAM_LABEL_MAP = {
    "手机类型": "手机类型",
    "操作系统": "操作系统",
    "CPU型号": "处理器",
    "CPU频率": "CPU频率",
    "CPU核数": "CPU核数",
    "GPU型号": "GPU",
    "运行内存": "内存",
    "机身容量": "存储",
    "电池容量": "电池",
    "电池类型": "电池类型",
    "屏幕尺寸": "屏幕",
    "屏幕分辨率": "屏幕分辨率",
    "屏幕材质": "屏幕材质",
    "摄像头": "摄像头参数",
    "前置摄像头": "前置摄像头",
    "后置摄像头": "后置摄像头",
    "网络制式": "网络类型",
    "SIM卡类型": "SIM卡类型",
    "机身尺寸": "机身尺寸",
    "机身重量": "机身重量",
    "指纹识别": "指纹识别",
    "NFC": "NFC",
    "蓝牙": "蓝牙",
    "WiFi": "WLAN功能",
    "GPS": "定位导航",
    "传感器": "感应器",
    "充电": "充电",
    "数据接口": "机身接口",
    "颜色": "机身颜色",
    "品牌": "品牌",
    "型号": "型号",
}


def fetch_page(url: str, encoding: str = "gbk") -> Optional[str]:
    """获取页面内容"""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(
                url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            resp.encoding = encoding
            return resp.text
        except Exception as e:
            logger.warning(f"获取 {url} 失败 (尝试 {attempt+1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(random.uniform(2, 5))
    return None


def parse_list_page(html: str) -> List[Dict[str, str]]:
    """解析列表页，提取产品 ID、名称、价格、上市时间"""
    soup = BeautifulSoup(html, "html.parser")
    products = []

    # CNMO 列表页结构：<li> 标签内包含产品信息
    for li in soup.select("li"):
        name_tag = li.select_one("a.name, a[title]")
        if not name_tag:
            continue
        name = name_tag.get("title", "").strip()
        href = name_tag.get("href", "").strip()

        # 提取产品 ID
        pid_match = re.search(r"index(\d+)", href)
        if not pid_match:
            continue
        pid = pid_match.group(1)

        # 提取价格
        price_tag = li.select_one("p.price, span.price, .red span")
        price = price_tag.text.strip() if price_tag else ""

        # 提取上市时间
        time_tag = li.select_one("p.red span, .time")
        launch_time = time_tag.text.strip() if time_tag else ""

        products.append({
            "id": pid,
            "name": name,
            "price": price,
            "launch_time": launch_time,
        })

    return products


def parse_detail_page(html: str) -> Dict[str, str]:
    """解析参数页 HTML，提取手机参数。
    CNMO 参数页结构：<p paramId="23" paramName="屏幕尺寸" paramValue="5.99英寸">
    """
    soup = BeautifulSoup(html, "html.parser")
    params = {}

    # 从 p[paramName][paramValue] 属性提取参数（属性名首字母大写）
    for p_tag in soup.find_all("p", paramname=True, paramvalue=True):
        name = p_tag.get("paramname", "").strip()
        value = p_tag.get("paramvalue", "").strip()
        if name and value:
            mapped = PARAM_LABEL_MAP.get(name, name)
            if mapped not in params:
                params[mapped] = value

    # 备选：从 div.left h3 + div.right p 提取
    if not params:
        for li in soup.select("li"):
            left = li.select_one(".left h3, .left")
            right = li.select_one(".right p, .right")
            if left and right:
                name = left.text.strip()
                value = right.text.strip()
                if name and value and len(name) < 30:
                    mapped = PARAM_LABEL_MAP.get(name, name)
                    params[mapped] = value

    return params


def parse_main_page(html: str) -> Dict[str, str]:
    """解析详情页主页面，提取基本信息和简要参数"""
    soup = BeautifulSoup(html, "html.parser")
    params = {}

    # 提取手机名称
    for tag in soup.select("h1, .phone-title, .pro-title"):
        text = tag.text.strip()
        if text and text != "手机大全" and len(text) > 2:
            params["型号"] = text
            break

    # 提取价格
    for tag in soup.select(".price, .pro-price, .red.f20"):
        text = tag.text.strip()
        if "¥" in text or "￥" in text:
            params["价格"] = text
            break

    # 提取简要参数（主页的 p 标签中的参数）
    for p_tag in soup.select("p"):
        text = p_tag.text.strip()
        # 匹配 "CPU型号：xxx" 或 "操作系统：xxx" 格式
        for label in ["CPU型号", "操作系统", "运行内存", "电池容量", "屏幕尺寸", "屏幕分辨率",
                       "后置摄像头", "前置摄像头", "核心数"]:
            if label in text:
                val = text.split(label, 1)[-1].lstrip("：:").strip()
                if val:
                    mapped = PARAM_LABEL_MAP.get(label, label)
                    params[mapped] = val

    return params


def load_progress() -> Dict:
    """加载爬取进度"""
    path = os.path.join(working_dir, PROGRESS_FILE)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed_pages": [], "completed_ids": [], "total_phones": 0}


def save_progress(progress: Dict):
    """保存爬取进度"""
    path = os.path.join(working_dir, PROGRESS_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def crawl(args):
    """主爬取逻辑"""
    today = date.today().strftime("%Y%m%d")
    output_file = os.path.join(data_dir, f"cnmo_phones_{today}.json")

    progress = load_progress()
    completed_pages = set(progress.get("completed_pages", []))
    completed_ids = set(progress.get("completed_ids", []))
    all_phones = []

    # 第1步：爬取列表页
    if args.step in (1, 0):
        max_pages = args.max_pages or 165
        logger.info(f"开始爬取 CNMO 列表页，最多 {max_pages} 页")

        for page in range(1, max_pages + 1):
            if page in completed_pages:
                logger.info(f"第 {page} 页已完成，跳过")
                continue

            url = LIST_URL.format(page=page)
            logger.info(f"爬取列表页: {url}")

            html = fetch_page(url)
            if not html:
                logger.error(f"第 {page} 页获取失败，停止")
                break

            products = parse_list_page(html)
            logger.info(f"第 {page} 页提取到 {len(products)} 个产品")

            for p in products:
                if p["id"] not in completed_ids:
                    all_phones.append(p)

            completed_pages.add(page)
            progress["completed_pages"] = sorted(completed_pages)
            progress["total_phones"] = len(completed_ids) + len(all_phones)
            save_progress(progress)

            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        # 保存列表页结果
        list_file = os.path.join(data_dir, f"cnmo_products_{today}.json")
        with open(list_file, "w", encoding="utf-8") as f:
            json.dump(all_phones, f, ensure_ascii=False, indent=2)
        logger.info(f"列表页完成，共 {len(all_phones)} 个新产品，保存到 {list_file}")

    # 第2步：爬取详情页
    if args.step in (2, 0):
        if not all_phones:
            # 从列表文件加载
            list_file = os.path.join(data_dir, f"cnmo_products_{today}.json")
            if os.path.exists(list_file):
                with open(list_file, "r", encoding="utf-8") as f:
                    all_phones = json.load(f)
            else:
                # 尝试找最近的列表文件
                import glob
                list_files = sorted(glob.glob(os.path.join(data_dir, "cnmo_products_*.json")), reverse=True)
                if list_files:
                    with open(list_files[0], "r", encoding="utf-8") as f:
                        all_phones = json.load(f)
                    logger.info(f"加载历史列表文件: {list_files[0]}")

        to_crawl = [p for p in all_phones if p["id"] not in completed_ids]
        if args.max_phones:
            to_crawl = to_crawl[:args.max_phones]

        logger.info(f"开始爬取详情页，共 {len(to_crawl)} 个产品")

        detailed_phones = []
        lock = threading.Lock()
        save_counter = 0
        step2_start = time.time()

        def crawl_one_phone(p, idx):
            """爬取单个手机详情，返回 (params, pid) 或 None"""
            pid = p["id"]
            main_url = DETAIL_URL.format(pid=pid)
            logger.info(f"[{idx}/{len(to_crawl)}] {p['name']} ({pid})")

            # 先获取主页面（获取基本信息 + param URL）
            main_html = fetch_page(main_url)
            if not main_html:
                logger.warning(f"主页面获取失败: {pid}")
                return None

            # 提取 param URL
            param_url = None
            soup = BeautifulSoup(main_html, "html.parser")
            for a_tag in soup.select('a[href*="param.shtml"]'):
                href = a_tag.get("href", "")
                if href:
                    param_url = urljoin(BASE_URL, href)
                    break

            # 从主页面提取基本信息
            main_params = parse_main_page(main_html)

            # 从参数页提取详细参数
            detail_params = {}
            if param_url:
                param_html = fetch_page(param_url)
                if param_html:
                    detail_params = parse_detail_page(param_html)
                time.sleep(random.uniform(0.5, 1.5))

            # 合并参数（参数页优先，主页面补充）
            params = detail_params.copy()
            for k, v in main_params.items():
                if k not in params or not params[k]:
                    params[k] = v

            # 补充列表信息
            params["手机ID"] = pid
            if "型号" not in params or not params.get("型号"):
                params["型号"] = p["name"]
            if "价格" not in params or not params.get("价格"):
                params["价格"] = p.get("price", "")
            if "上市时间" not in params or not params.get("上市时间"):
                params["上市时间"] = p.get("launch_time", "")
            params["数据来源"] = "CNMO"

            # 线程间延迟（并发下总请求间隔降低）
            time.sleep(random.uniform(0.3, 0.8))

            return (params, pid)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {}
            for i, p in enumerate(to_crawl, 1):
                futures[executor.submit(crawl_one_phone, p, i)] = p

            for future in as_completed(futures):
                # 时间限制检查
                if args.time_limit and args.time_limit > 0:
                    elapsed = time.time() - step2_start
                    if elapsed > args.time_limit:
                        logger.warning(
                            f"达到时间限制 {args.time_limit}秒，"
                            f"已处理 {len(detailed_phones)}/{len(to_crawl)}，提前退出"
                        )
                        for f in futures:
                            f.cancel()
                        break

                result = future.result()
                if result:
                    params, pid = result
                    with lock:
                        detailed_phones.append(params)
                        completed_ids.add(pid)
                        save_counter += 1

                        # 每 10 个产品保存一次进度
                        if save_counter >= 10:
                            progress["completed_ids"] = sorted(completed_ids)
                            progress["total_phones"] = len(detailed_phones)
                            save_progress(progress)
                            save_counter = 0

        # 最终保存进度
        progress["completed_ids"] = sorted(completed_ids)
        progress["total_phones"] = len(detailed_phones)
        save_progress(progress)

        # 保存详情数据
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(detailed_phones, f, ensure_ascii=False, indent=2)
        logger.info(f"详情页完成，共 {len(detailed_phones)} 条，保存到 {output_file}")

    # 第3步：生成摘要
    if args.step in (3, 0):
        if os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8") as f:
                phones = json.load(f)
        else:
            # 找最新文件
            import glob
            files = sorted(glob.glob(os.path.join(data_dir, "cnmo_phones_*.json")), reverse=True)
            if files:
                with open(files[0], "r", encoding="utf-8") as f:
                    phones = json.load(f)
            else:
                phones = []

        brands = set()
        for p in phones:
            brand = p.get("品牌", "")
            if not brand:
                # 从型号推导品牌
                name = p.get("型号", "")
                for b in ["华为", "荣耀", "小米", "红米", "OPPO", "vivo", "iQOO", "一加", "真我", "三星", "苹果", "努比亚", "魅族"]:
                    if name.startswith(b):
                        brand = b
                        break
            if brand:
                brands.add(brand)

        logger.info(f"=== CNMO 爬取摘要 ===")
        logger.info(f"总计: {len(phones)} 款手机")
        logger.info(f"品牌数: {len(brands)}")
        logger.info(f"输出文件: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="CNMO 手机爬虫")
    parser.add_argument("--step", type=int, default=0, choices=[0, 1, 2, 3],
                        help="1=列表页, 2=详情页, 3=摘要, 0=全部")
    parser.add_argument("--max-pages", type=int, default=0,
                        help="最大列表页数（0=全部165页）")
    parser.add_argument("--max-phones", type=int, default=0,
                        help="最大爬取手机数（0=全部）")
    parser.add_argument("--time-limit", type=int, default=0,
                        help="时间限制（秒），0=不限制")

    args = parser.parse_args()

    start_time = time.time()
    try:
        crawl(args)
    except KeyboardInterrupt:
        logger.info("用户中断，进度已保存")
    finally:
        elapsed = time.time() - start_time
        logger.info(f"总耗时: {elapsed:.0f} 秒")


if __name__ == "__main__":
    main()