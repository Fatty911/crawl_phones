#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CNMO（手机中国）爬虫 - 爬取全部手机型号的配置信息
https://product.cnmo.com/all/product_t1_p{page}.html

列表页：服务端渲染 HTML，GBK 编码，每页约 32 款
详情页：https://product.cnmo.com/cell_phone/index{id}.shtml
参数页：https://product.cnmo.com/cell_phone/{id}/param.shtml
"""

import os
import sys
import json
import glob
import time
import random
import re
import csv
import argparse
import logging
from datetime import datetime, date
from typing import List, Dict, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

# 字段标准化映射（与 merge_phones.py 保持一致）
HEADER_MAP = {
    'launch_time': '上市时间',
    '国内发布时间': '上市时间',
    '发布时间': '上市时间',
    '发布日期': '上市时间',
    '上市日期': '上市时间',
    '上市时间': '上市时间',
    'price': '价格',
    '电商报价': '价格',
    '参考报价': '价格',
    '售价': '价格',
    '报价': '价格',
    '手机名称': '型号',
    'name': '型号',
    '产品名称': '型号',
    'CPU型号': '处理器',
    'CPU': '处理器',
    'CPU品牌': '处理器',
    '处理器型号': '处理器',
    '处理器': '处理器',
    '屏幕尺寸': '屏幕',
    '主屏尺寸': '屏幕',
    '屏幕': '屏幕',
    '分辨率': '屏幕分辨率',
    '主屏分辨率': '屏幕分辨率',
    '屏幕分辨率': '屏幕分辨率',
    '后置摄像头': '摄像头参数',
    '前置摄像头': '摄像头参数',
    '摄像头': '摄像头参数',
    '摄像头总数': '摄像头参数',
    '摄像头特色': '摄像头参数',
    '电池容量': '电池',
    '电池': '电池',
    '电池类型': '电池类型',
    'RAM容量': '内存',
    '运行内存': '内存',
    '内存': '内存',
    'ROM容量': '存储',
    '机身存储': '存储',
    '存储': '存储',
    '机身容量': '存储',
    '机身尺寸': '机身尺寸',
    '尺寸': '机身尺寸',
    '长度': '机身长度',
    '宽度': '机身宽度',
    '厚度': '机身厚度',
    '重量': '机身重量',
    '机身重量': '机身重量',
    '网络制式': '网络类型',
    '网络类型': '网络类型',
    'SIM卡类型': 'SIM卡类型',
    '指纹识别': '指纹识别',
    'NFC': 'NFC',
    '蓝牙': '蓝牙',
    'WiFi': 'WLAN功能',
    'GPS': '定位导航',
    '传感器': '感应器',
    '充电': '充电',
    '数据接口': '机身接口',
    '颜色': '机身颜色',
    'GPU型号': 'GPU',
    'CPU频率': 'CPU频率',
    'CPU核数': 'CPU核数',
    '屏幕材质': '屏幕材质',
    '手机类型': '手机类型',
    '操作系统': '操作系统',
}


def normalize_phone_fields(phone: Dict) -> Dict:
    """将手机数据的字段名标准化为统一格式"""
    normalized = {}
    for key, value in phone.items():
        clean_key = key.rstrip('：:').strip()
        new_key = HEADER_MAP.get(clean_key, clean_key)
        if new_key in normalized and not normalized[new_key] and value:
            normalized[new_key] = value
        elif new_key not in normalized:
            normalized[new_key] = value
        elif value and normalized[new_key]:
            if len(str(value)) > len(str(normalized[new_key])):
                normalized[new_key] = value
    return normalized


# 品牌推导（兜底，从型号名推导）
BRAND_PATTERNS = [
    ('苹果', ['iphone', 'ipad', 'apple']),
    ('华为', ['huawei', '华为']),
    ('荣耀', ['honor', '荣耀']),
    ('小米', ['xiaomi', '小米', 'poco']),
    ('红米', ['redmi', '红米']),
    ('OPPO', ['oppo']),
    ('一加', ['oneplus', '一加']),
    ('真我', ['realme', '真我']),
    ('vivo', ['vivo']),
    ('iQOO', ['iqoo']),
    ('三星', ['samsung', '三星']),
    ('魅族', ['meizu', '魅族']),
    ('中兴', ['zte', '中兴']),
    ('努比亚', ['nubia', '努比亚']),
    ('联想', ['lenovo', '联想']),
    ('摩托罗拉', ['moto', 'motorola', '摩托罗拉']),
    ('索尼', ['sony', '索尼', 'xperia']),
    ('谷歌', ['google', 'pixel']),
    ('诺基亚', ['nokia', '诺基亚']),
    ('Nothing', ['nothing']),
    ('传音', ['tecno', 'itel', 'infinix']),
]


def derive_brand_from_name(name):
    """从手机型号名称推导品牌"""
    if not name:
        return ''
    name_lower = name.lower()
    for brand_name, patterns in BRAND_PATTERNS:
        for pat in patterns:
            if pat in name_lower:
                return brand_name
    return ''


def extract_release_year(phone):
    """从手机数据中提取发布年份"""
    for key in ['上市时间', 'launch_time', '国内发布时间', '发布时间', '发布日期', '上市日期']:
        value = phone.get(key, '')
        if value:
            match = re.search(r'(\d{4})', str(value))
            if match:
                return int(match.group(1))
    return None


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

parser = argparse.ArgumentParser(description='CNMO手机爬虫')
parser.add_argument('--step', type=int, choices=[1, 2, 3], help='运行指定步骤')
parser.add_argument('--time-limit', type=int, default=0, help='每步最大运行时间(秒)，0表示不限制')
parser.add_argument('--max-pages', type=int, default=0, help='第一步最多爬取页数，0表示不限制')
parser.add_argument('--max-phones', type=int, default=0, help='最多爬取手机数，0表示不限制')
parser.add_argument('--auto', action='store_true', help='全自动模式：未完成则exit code 10')
parser.add_argument('--restart', action='store_true', help='重置进度，从头开始')
parser.add_argument('--incremental', action='store_true', help='增量模式：只爬取新增手机')
parser.add_argument('--debug-limit', type=int, default=0, help='调试模式限制爬取数量（配合 --incremental 使用）')
args = parser.parse_args()

MAX_TIME_PER_STEP = args.time_limit
MAX_PAGES_PER_RUN = args.max_pages
MAX_PHONES_PER_RUN = args.max_phones
AUTO_MODE = args.auto
INCREMENTAL_MODE = args.incremental

if args.debug_limit > 0:
    INCREMENTAL_MODE = True
    MAX_PHONES_PER_RUN = args.debug_limit
    logger.info(f"调试模式：限制爬取 {args.debug_limit} 个手机，启用增量扫描模式")

working_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cnmo_dir = os.path.join(working_dir, 'crawl_state', 'cnmo')
cnmo_json_dir = os.path.join(cnmo_dir, 'json')
data_dir = os.path.join(working_dir, 'data')
os.makedirs(data_dir, exist_ok=True)

for d in [cnmo_dir, cnmo_json_dir]:
    if not os.path.exists(d):
        os.makedirs(d)

progress_file = os.path.join(cnmo_dir, 'progress.json')
if os.path.exists(progress_file) and not args.restart:
    with open(progress_file, 'r', encoding='utf-8') as f:
        progress = json.load(f)
    logger.info('从上次进度继续（使用 --restart 可重新开始）')
else:
    progress = {
        'crawled_pages': [],
        'crawled_phones': [],
        'current_page': 1,
        'total_phones': 0
    }
    logger.info('初始化新进度')

CURRENT_YEAR = 2026
MIN_YEAR = 2021
CRAWL_MIN_DELAY_SECONDS = float(os.getenv("CRAWL_MIN_DELAY_SECONDS", "8"))
CRAWL_MAX_DELAY_SECONDS = float(os.getenv("CRAWL_MAX_DELAY_SECONDS", "20"))
REQUEST_TIMEOUT = 15

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Referer': 'https://product.cnmo.com/all/product.html',
}

BASE_URL = "https://product.cnmo.com"
LIST_URL = f"{BASE_URL}/all/product_t1_p{{page}}.html"
DETAIL_URL = f"{BASE_URL}/cell_phone/index{{pid}}.shtml"
PARAM_URL = f"{BASE_URL}/cell_phone/{{pid}}/param.shtml"

_DOMAIN = urlparse(BASE_URL).netloc


def resolve_param_url(href: str, page_url: str = f"{BASE_URL}/") -> Optional[str]:
    """Resolve a param.shtml href from a CNMO page to an absolute URL.

    Handles protocol-relative (//product.cnmo.com/...), path-absolute with
    duplicated domain (/product.cnmo.com/...), absolute, and relative hrefs.
    """
    if not href or not href.strip():
        return None
    href = href.strip()
    domain_path_prefix = f"/{_DOMAIN}"
    if href.startswith(domain_path_prefix):
        if not href.startswith(f"{domain_path_prefix}/"):
            return None
        href = href[len(domain_path_prefix):]

    resolved = urljoin(page_url, href)
    parsed = urlparse(resolved)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != _DOMAIN:
        return None
    if not parsed.path.endswith("/param.shtml"):
        return None
    return resolved


def save_progress():
    with open(progress_file, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def human_delay(label=""):
    delay = random.uniform(CRAWL_MIN_DELAY_SECONDS, CRAWL_MAX_DELAY_SECONDS)
    if label:
        logger.info(f"{label}后等待 {delay:.1f} 秒，模拟人工浏览节奏")
    time.sleep(delay)


def get_session():
    session = requests.Session()
    session.headers.update(HEADERS)

    retry_strategy = Retry(
        total=3,
        status_forcelist=[429, 500, 502, 503, 504],
        backoff_factor=0.5
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    proxy_url = os.environ.get('HTTP_PROXY') or os.environ.get('HTTPS_PROXY')
    if proxy_url:
        session.proxies = {
            'http': proxy_url,
            'https': proxy_url
        }
        logger.info(f"使用代理: {proxy_url}")

    return session


def crawl_list_page(session: requests.Session, page: int) -> List[Dict]:
    url = LIST_URL.format(page=page)
    logger.info(f"爬取列表页: {url}")

    try:
        human_delay("列表页请求")
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = 'gbk'
    except Exception as e:
        logger.error(f"列表页请求失败: {e}")
        raise RuntimeError(f"CNMO列表页请求失败 page={page}: {e}") from e

    soup = BeautifulSoup(resp.text, 'html.parser')
    products = []

    for li in soup.select("li"):
        name_tag = li.select_one("a.name, a[title]")
        if not name_tag:
            continue
        name = name_tag.get("title", "").strip()
        href = name_tag.get("href", "").strip()

        pid_match = re.search(r"index(\d+)", href)
        if not pid_match:
            continue
        pid = pid_match.group(1)

        price_tag = li.select_one("p.price, span.price, .red span")
        price = price_tag.text.strip() if price_tag else ""

        time_tag = li.select_one("p.red span, .time")
        launch_time = time_tag.text.strip() if time_tag else ""

        products.append({
            "id": pid,
            "name": name,
            "price": price,
            "launch_time": launch_time,
        })

    if page == 1 and not products:
        raise RuntimeError("CNMO列表首屏返回200但未解析到产品，拒绝当作扫描完成")

    return products


def crawl_detail_page(session: requests.Session, phone_id: str) -> Optional[Dict]:
    """爬取详情页（主页面 + 参数页）"""
    url = DETAIL_URL.format(pid=phone_id)
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = 'gbk'
    except Exception as e:
        logger.warning(f"详情页请求失败 {phone_id}: {e}")
        return None

    soup = BeautifulSoup(resp.text, 'html.parser')
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

    # 提取简要参数
    for p_tag in soup.select("p"):
        text = p_tag.text.strip()
        for label in ["CPU型号", "操作系统", "运行内存", "电池容量", "屏幕尺寸", "屏幕分辨率",
                       "后置摄像头", "前置摄像头", "核心数"]:
            if label in text:
                val = text.split(label, 1)[-1].lstrip("：:").strip()
                if val:
                    params[label] = val

    # 查找参数页链接
    param_url = None
    for a_tag in soup.select('a[href*="param.shtml"]'):
        href = str(a_tag.get("href") or "")
        resolved = resolve_param_url(href, url)
        if resolved:
            param_url = resolved
            break

    # 爬取参数页
    if param_url:
        try:
            param_resp = session.get(param_url, timeout=REQUEST_TIMEOUT)
            param_resp.raise_for_status()
            param_resp.encoding = 'gbk'
            param_soup = BeautifulSoup(param_resp.text, 'html.parser')

            for p_tag in param_soup.find_all("p", paramname=True, paramvalue=True):
                name = p_tag.get("paramname", "").strip()
                value = p_tag.get("paramvalue", "").strip()
                if name and value:
                    params[name] = value

            # 备选提取
            if not any(k in ['屏幕尺寸', '电池容量', 'CPU型号'] for k in params):
                for li in param_soup.select("li"):
                    left = li.select_one(".left h3, .left")
                    right = li.select_one(".right p, .right")
                    if left and right:
                        name = left.text.strip()
                        value = right.text.strip()
                        if name and value and len(name) < 30:
                            params[name] = value
        except Exception as e:
            logger.warning(f"参数页爬取失败 {phone_id}: {e}")
            return None

    return params if params else None


def step1_crawl_list_and_detail():
    logger.info("=" * 70)
    logger.info("步骤1：爬取列表和详情页")
    logger.info("=" * 70)

    start_time = time.time()
    session = get_session()

    previous_rows = load(find_latest("cnmo_phones_*.json"))
    existing_ids = {os.path.splitext(f)[0] for f in os.listdir(cnmo_json_dir) if f.endswith('.json')}
    existing_ids.update(str(row.get('手机ID') or row.get('id') or '').strip() for row in previous_rows)
    existing_ids.update(str(phone_id).strip() for phone_id in progress.get('crawled_phones', []))
    existing_ids.discard('')
    phones_crawled = max(progress.get('total_phones', 0), len(existing_ids))
    run_crawled = 0

    # 增量模式：扫描列表页，只爬新增
    if INCREMENTAL_MODE:
        logger.info("增量模式：扫描列表页，检测新增手机...")
        all_phones = []
        scan_start_page = max(1, int(progress.get('incremental_scan_page', 1)))
        page = scan_start_page
        pages_scanned_this_run = 0
        scan_complete = False
        while True:
            products = crawl_list_page(session, page)
            if not products:
                scan_complete = True
                progress['incremental_scan_page'] = 1
                save_progress()
                break
            all_phones.extend(products)
            logger.info(f"第 {page} 页提取到 {len(products)} 个产品")
            page += 1
            pages_scanned_this_run += 1
            progress['incremental_scan_page'] = page
            save_progress()
            if MAX_PAGES_PER_RUN > 0 and pages_scanned_this_run >= MAX_PAGES_PER_RUN:
                break
            if MAX_TIME_PER_STEP > 0 and (time.time() - start_time) >= MAX_TIME_PER_STEP * 0.3:
                break

        new_phones = [p for p in all_phones if p['id'] not in existing_ids]
        logger.info(f"增量扫描完成：共 {len(all_phones)} 个型号，新增 {len(new_phones)} 个")

        if not new_phones:
            logger.info("未发现新增型号，无需爬取详情")
            progress['total_phones'] = phones_crawled
            save_progress()
            if not scan_complete and AUTO_MODE:
                logger.info("列表扫描受限，等待下次继续")
                sys.exit(10)
            return

        detail_failed = False
        for phone in new_phones:
            if MAX_TIME_PER_STEP > 0:
                elapsed = time.time() - start_time
                if elapsed >= MAX_TIME_PER_STEP:
                    logger.info(f"达到时间限制 ({MAX_TIME_PER_STEP}秒)，保存进度")
                    progress['incremental_scan_page'] = scan_start_page
                    progress['total_phones'] = phones_crawled
                    save_progress()
                    if AUTO_MODE:
                        logger.info('未完成，等待下次继续')
                        sys.exit(10)
                    return

            if MAX_PHONES_PER_RUN > 0 and run_crawled >= MAX_PHONES_PER_RUN:
                logger.info(f"达到手机数量限制 ({MAX_PHONES_PER_RUN}个)，保存进度")
                progress['incremental_scan_page'] = scan_start_page
                progress['total_phones'] = phones_crawled
                save_progress()
                if AUTO_MODE:
                    logger.info('达到数量上限，等待下次继续')
                    sys.exit(10)
                return

            phone_id = phone['id']
            logger.info(f"爬取详情: {phone['name']} ({phone_id})")

            detail = crawl_detail_page(session, phone_id)
            if detail:
                phone.update(detail)
                release_year = extract_release_year(phone)

                if release_year and release_year >= MIN_YEAR:
                    phone = normalize_phone_fields(phone)
                    if not phone.get('品牌'):
                        phone['品牌'] = derive_brand_from_name(phone.get('型号', phone.get('name', '')))
                    phone['数据来源'] = 'CNMO'

                    phone_file = os.path.join(cnmo_json_dir, f"{phone_id}.json")
                    with open(phone_file, 'w', encoding='utf-8') as f:
                        json.dump(phone, f, ensure_ascii=False, indent=2)

                    phones_crawled += 1
                    run_crawled += 1
                    if phone_id not in progress.setdefault('crawled_phones', []):
                        progress['crawled_phones'].append(phone_id)
                    save_progress()
                    logger.info(f"✓ 保存: {phone.get('型号', phone.get('name', '未知'))} ({release_year}年) - 本次{run_crawled}个，累计{phones_crawled}个")
                elif release_year:
                    logger.debug(f"跳过: {phone.get('name', '未知')} ({release_year}年) - 不在近五年范围内")
                else:
                    logger.debug(f"跳过: {phone.get('name', '未知')} - 无法获取发布年份")
            else:
                logger.warning(f"✗ 详情页爬取失败: {phone.get('name', '未知')}")
                detail_failed = True

        progress['total_phones'] = phones_crawled
        save_progress()
        logger.info(f"增量模式完成：本次新增 {run_crawled} 个手机，累计 {phones_crawled} 个")
        if detail_failed:
            progress['incremental_scan_page'] = scan_start_page
            save_progress()
            if AUTO_MODE:
                logger.info("存在详情页失败，等待下次重试")
                sys.exit(10)
            return
        if not scan_complete and AUTO_MODE:
            logger.info("列表扫描受限，等待下次继续")
            sys.exit(10)
        return

    # 全量模式
    page = progress.get('current_page', 1)
    pages_crawled_this_run = 0
    logger.info(f"从进度恢复: total_phones={phones_crawled}, page={page}")

    while True:
        if MAX_TIME_PER_STEP > 0:
            elapsed = time.time() - start_time
            if elapsed >= MAX_TIME_PER_STEP:
                logger.info(f"达到时间限制 ({MAX_TIME_PER_STEP}秒)，保存进度")
                save_progress()
                if AUTO_MODE:
                    logger.info('未完成，等待下次继续')
                    sys.exit(10)
                return

        if MAX_PAGES_PER_RUN > 0 and pages_crawled_this_run >= MAX_PAGES_PER_RUN:
            logger.info(f"达到页数限制，保存进度")
            save_progress()
            if AUTO_MODE:
                sys.exit(10)
            return

        if MAX_PHONES_PER_RUN > 0 and run_crawled >= MAX_PHONES_PER_RUN:
            logger.info(f"达到手机数量限制，保存进度")
            save_progress()
            if AUTO_MODE:
                sys.exit(10)
            return

        products = crawl_list_page(session, page)
        if not products:
            logger.info("列表页为空，停止爬取")
            break

        page_failed = False
        for phone in products:
            if MAX_TIME_PER_STEP > 0:
                elapsed = time.time() - start_time
                if elapsed >= MAX_TIME_PER_STEP:
                    logger.info(f"达到时间限制，保存进度")
                    progress['current_page'] = page
                    progress['total_phones'] = phones_crawled
                    save_progress()
                    if AUTO_MODE:
                        sys.exit(10)
                    return

            if MAX_PHONES_PER_RUN > 0 and run_crawled >= MAX_PHONES_PER_RUN:
                progress['current_page'] = page
                progress['total_phones'] = phones_crawled
                save_progress()
                if AUTO_MODE:
                    sys.exit(10)
                return

            phone_id = phone['id']
            if phone_id in progress.get('crawled_phones', []):
                continue

            detail = crawl_detail_page(session, phone_id)
            if detail:
                phone.update(detail)
                release_year = extract_release_year(phone)

                if release_year and release_year >= MIN_YEAR:
                    phone = normalize_phone_fields(phone)
                    if not phone.get('品牌'):
                        phone['品牌'] = derive_brand_from_name(phone.get('型号', phone.get('name', '')))
                    phone['数据来源'] = 'CNMO'

                    phone_file = os.path.join(cnmo_json_dir, f"{phone_id}.json")
                    with open(phone_file, 'w', encoding='utf-8') as f:
                        json.dump(phone, f, ensure_ascii=False, indent=2)

                    phones_crawled += 1
                    run_crawled += 1
                    progress['crawled_phones'].append(phone_id)
                    save_progress()
                    logger.info(f"✓ 保存: {phone.get('型号', phone.get('name', '未知'))} ({release_year}年) - 共{phones_crawled}个")
                elif release_year:
                    logger.debug(f"跳过: {phone.get('name', '未知')} ({release_year}年)")
                else:
                    logger.debug(f"跳过: {phone.get('name', '未知')} - 无法获取发布年份")
            else:
                logger.warning(f"✗ 详情页爬取失败: {phone.get('name', '未知')}")
                page_failed = True

        if page_failed:
            progress['current_page'] = page
            progress['total_phones'] = phones_crawled
            save_progress()
            if AUTO_MODE:
                logger.info("本页存在详情失败，保留页码等待下次重试")
                sys.exit(10)
            return

        progress['crawled_pages'].append(page)
        progress['current_page'] = page + 1
        progress['total_phones'] = phones_crawled
        save_progress()
        pages_crawled_this_run += 1
        page += 1

    logger.info(f"步骤1完成！共爬取 {phones_crawled} 个手机")


def step2_parse_and_merge():
    logger.info("=" * 70)
    logger.info("步骤2：解析和合并数据")
    logger.info("=" * 70)

    fresh_phones = []
    for filename in os.listdir(cnmo_json_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(cnmo_json_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    phone_data = json.load(f)
                    phone_data = normalize_phone_fields(phone_data)
                    fresh_phones.append(phone_data)
            except Exception as e:
                logger.error(f"读取文件失败: {filepath} - {e}")

    logger.info(f"本次缓存读取 {len(fresh_phones)} 个手机数据")

    prev_file = find_latest("cnmo_phones_*.json")
    previous_phones = load(prev_file)
    merged = {}
    order = []
    for phone in previous_phones + fresh_phones:
        normalized = normalize_phone_fields(phone)
        key = cnmo_row_identity(normalized)
        if key not in merged:
            order.append(key)
        merged[key] = normalized
    all_phones = [merged[key] for key in order]
    if prev_file:
        logger.info(f"累积上次数据: {os.path.basename(prev_file)} ({len(previous_phones)} 条)，本次缓存优先覆盖")
    if not all_phones:
        logger.warning("没有任何手机数据，将输出空文件")

    all_phones.sort(key=lambda x: x.get('上市时间', ''), reverse=True)

    today = date.today().strftime("%Y%m%d")
    output_file = os.path.join(data_dir, f"cnmo_phones_{today}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_phones, f, ensure_ascii=False, indent=2)
    logger.info(f"合并数据已保存到: {output_file}")

    csv_file = os.path.join(data_dir, f"cnmo_phones_{today}.csv")
    if all_phones:
        all_keys = set()
        for phone in all_phones:
            all_keys.update(phone.keys())
        fixed_keys = ['手机ID', '型号', '数据来源', '上市时间', '价格']
        other_keys = sorted([k for k in all_keys if k not in fixed_keys])
        fieldnames = fixed_keys + other_keys
        with open(csv_file, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for phone in all_phones:
                writer.writerow({key: phone.get(key, '') for key in fieldnames})
        logger.info(f"CSV数据已保存到: {csv_file}")

    return all_phones


def step3_generate_summary():
    logger.info("=" * 70)
    logger.info("步骤3：生成统计摘要")
    logger.info("=" * 70)

    total_phones = len(progress.get('crawled_phones', []))
    total_pages = len(progress.get('crawled_pages', []))
    logger.info(f"爬取页数: {total_pages}")
    logger.info(f"爬取手机数: {total_phones}")

    brand_count = {}
    for filename in os.listdir(cnmo_json_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(cnmo_json_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    phone_data = json.load(f)
                    brand = phone_data.get('品牌', '未知')
                    brand_count[brand] = brand_count.get(brand, 0) + 1
            except:
                pass

    logger.info("品牌分布:")
    for brand, count in sorted(brand_count.items(), key=lambda x: x[1], reverse=True)[:10]:
        logger.info(f"  {brand}: {count} 个")


def find_latest(pattern):
    files = glob.glob(os.path.join(data_dir, pattern))
    if not files:
        files = glob.glob(os.path.join(working_dir, pattern))
    if not files:
        return None
    data_files = [f for f in files if 'progress' not in f and 'manifest' not in f]
    if not data_files:
        data_files = files
    def sort_key(path):
        basename = os.path.basename(path)
        match = re.search(r'cnmo_phones_(\d{8})\.json$', basename)
        crawl_date = match.group(1) if match else ''
        canonical = basename.startswith('cnmo_phones_')
        return crawl_date, canonical, basename

    return max(data_files, key=sort_key)


def cnmo_row_identity(phone):
    phone_id = str(phone.get('手机ID') or phone.get('id') or '').strip()
    if phone_id:
        return f"id:{phone_id}"
    model = re.sub(r'\s+', '', str(phone.get('型号') or phone.get('name') or '')).lower()
    return f"model:{model}"


def load(path):
    if not path or not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    logger.info("CNMO手机参数爬虫")
    logger.info("=" * 70)

    if args.step:
        if args.step == 1:
            step1_crawl_list_and_detail()
        elif args.step == 2:
            step2_parse_and_merge()
        elif args.step == 3:
            step3_generate_summary()
    else:
        step1_crawl_list_and_detail()
        step2_parse_and_merge()
        step3_generate_summary()


if __name__ == '__main__':
    main()