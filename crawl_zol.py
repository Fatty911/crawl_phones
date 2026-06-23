#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
from bs4 import BeautifulSoup

# 字段标准化映射（与 merge_phones.py 保持一致）
HEADER_MAP = {
    '国内发布时间': '上市时间',
    '发布时间': '上市时间',
    '发布日期': '上市时间',
    '上市日期': '上市时间',
    '电商报价': '价格',
    '售价': '价格',
    '手机名称': '型号',
    'name': '型号',
    '产品名称': '型号',
    'CPU型号': '处理器',
    'CPU': '处理器',
    '处理器型号': '处理器',
    '处理器': '处理器',
    '屏幕尺寸': '屏幕',
    '主屏尺寸': '屏幕',
    '屏幕': '屏幕',
    '分辨率': '屏幕分辨率',
    '主屏分辨率': '屏幕分辨率',
    '屏幕分辨率': '屏幕分辨率',
    '后置摄像头': '摄像头参数',
    '后置摄像头像素': '摄像头参数',
    '前置摄像头': '摄像头参数',
    '前置摄像头像素': '摄像头参数',
    '摄像头名称': '摄像头参数',
    '摄像头总数': '摄像头参数',
    '摄像头特色': '摄像头参数',
    '变焦倍数': '摄像头参数',
    '传感器尺寸': '摄像头参数',
    '镜头片数': '摄像头参数',
    '焦距': '摄像头参数',
    '其他摄像头参数': '摄像头参数',
    '电池容量': '电池',
    '电池容量(mAh)': '电池',
    '电池': '电池',
    'RAM容量': '内存',
    '运行内存': '内存',
    '运行内存(RAM)': '内存',
    '内存': '内存',
    'ROM容量': '存储',
    '机身存储': '存储',
    '存储': '存储',
    '机身尺寸': '机身尺寸',
    '尺寸': '机身尺寸',
    '长度': '机身长度',
    '宽度': '机身宽度',
    '厚度': '机身厚度',
    '重量': '机身重量',
    '机身重量': '机身重量',
}

def normalize_phone_fields(phone: Dict) -> Dict:
    """将手机数据的字段名标准化为统一格式"""
    normalized = {}
    for key, value in phone.items():
        # 清理键名：去除冒号和空白
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

# 手机品牌推导
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

parser = argparse.ArgumentParser(description='中关村在线手机爬虫')
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

# 调试模式：强制开启增量扫描模式，并限制爬取数量
if args.debug_limit > 0:
    INCREMENTAL_MODE = True
    MAX_PHONES_PER_RUN = args.debug_limit
    logger.info(f"调试模式：限制爬取 {args.debug_limit} 个手机，启用增量扫描模式")

working_dir = os.path.dirname(os.path.abspath(__file__))
zol_dir = os.path.join(working_dir, 'zol')
zol_json_dir = os.path.join(zol_dir, 'json')
zol_exception_dir = os.path.join(zol_dir, 'exception')

for d in [zol_dir, zol_json_dir, zol_exception_dir]:
    if not os.path.exists(d):
        os.makedirs(d)

progress_file = os.path.join(zol_dir, 'progress.json')
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
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Cache-Control': 'max-age=0',
    'Referer': 'https://detail.zol.com.cn/'
}

BASE_URL = "https://detail.zol.com.cn"


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
    url = f"{BASE_URL}/cell_phone_index/subcate57_list_{page}.html"
    logger.info(f"爬取列表页: {url}")
    
    try:
        human_delay("列表页请求")
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.encoding = 'gbk'
        
        if resp.status_code != 200:
            logger.warning(f"请求失败: {url} (状态码: {resp.status_code})")
            return []
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        links = soup.find_all('a', href=re.compile(r'/cell_phone/index\d+\.shtml'))
        
        phones = []
        for link in links:
            href = link.get('href', '')
            phone_id_match = re.search(r'index(\d+)', href)
            if phone_id_match:
                phone_id = phone_id_match.group(1)
                phone_name = link.get_text(strip=True)
                if phone_name and len(phone_name) > 2:
                    phones.append({
                        'id': phone_id,
                        'name': phone_name,
                        'url': f"{BASE_URL}{href}",
                        'source': '中关村在线'
                    })
        
        logger.info(f"找到 {len(phones)} 个手机")
        return phones
        
    except Exception as e:
        logger.error(f"爬取列表页异常: {e}")
        return []


def crawl_detail_page(session: requests.Session, phone_id: str) -> Optional[Dict]:
    url = f"{BASE_URL}/cell_phone/index{phone_id}.shtml"
    logger.info(f"爬取详情页: {url}")
    
    try:
        human_delay("详情页请求")
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.encoding = 'gbk'
        
        if resp.status_code != 200:
            logger.warning(f"请求失败: {url} (状态码: {resp.status_code})")
            return None
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        detail = {
            'phone_id': phone_id,
            'url': url,
            'crawl_time': datetime.now().isoformat()
        }
        
        title = soup.find('h1')
        if title:
            detail['name'] = title.get_text(strip=True)
        
        param_link = soup.find('a', string=re.compile('参数'))
        if param_link:
            param_href = param_link.get('href', '')
            detail['param_url'] = f"{BASE_URL}{param_href}"
        
        labels = soup.find_all('label')
        for label in labels:
            label_text = label.get_text(strip=True)
            next_elem = label.find_next_sibling()
            if next_elem:
                value = next_elem.get_text(strip=True)
                if label_text and value:
                    key = label_text.rstrip('：:').strip()
                    if key:
                        detail[key] = value
        
        return detail
        
    except Exception as e:
        logger.error(f"爬取详情页异常: {e}")
        return None


def crawl_param_page(session: requests.Session, phone_id: str, category_id: str = '2140') -> Optional[Dict]:
    url = f"{BASE_URL}/{category_id}/{phone_id}/param.shtml"
    logger.info(f"爬取参数页: {url}")
    
    try:
        human_delay("参数页请求")
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.encoding = 'gbk'
        
        if resp.status_code != 200:
            logger.warning(f"请求失败: {url} (状态码: {resp.status_code})")
            return None
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        tables = soup.find_all('table')
        
        params = {}
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    key = cells[0].get_text(strip=True)
                    value = cells[1].get_text(strip=True)
                    if key and value:
                        key = re.sub(r'\s+', ' ', key).strip()
                        params[key] = value
        
        logger.info(f"提取 {len(params)} 个参数")
        return params
        
    except Exception as e:
        logger.error(f"爬取参数页异常: {e}")
        return None


def extract_release_year(detail: Dict) -> Optional[int]:
    time_fields = ['国内发布时间', '上市日期', '发布时间', '发布日期', '上市时间']
    for field in time_fields:
        if field in detail:
            time_str = detail[field]
            year_match = re.search(r'(\d{4})', time_str)
            if year_match:
                year = int(year_match.group(1))
                if 2000 <= year <= 2030:
                    return year

    return None


def _get_existing_phone_ids() -> set:
    """获取本地已存手机的ID集合（基于json文件实际存在性）"""
    existing = set()
    if not os.path.exists(zol_json_dir):
        return existing
    for filename in os.listdir(zol_json_dir):
        if filename.endswith('.json'):
            phone_id = filename.replace('.json', '')
            existing.add(phone_id)
    return existing


def _scan_all_models(session: requests.Session) -> List[Dict]:
    """全量扫描所有型号（仅收集基础信息，不爬详情）"""
    logger.info("=" * 70)
    logger.info("增量扫描模式：全量扫描所有型号...")
    logger.info("=" * 70)

    all_phones = []
    page = 1
    while True:
        phones = crawl_list_page(session, page)
        if not phones:
            break
        all_phones.extend(phones)
        # 调试/限制模式下：可以提前终止扫描
        if MAX_PHONES_PER_RUN > 0 and len(all_phones) >= MAX_PHONES_PER_RUN * 3:
            logger.info(f"接近数量限制，提前终止型号扫描（已扫描 {len(all_phones)} 个型号）")
            break
        page += 1
        # 安全限制：防止无限循环
        if page > 100:
            logger.warning("警告：分页超过100页，强制结束以防止无限循环")
            break

    logger.info(f"全量扫描完成：共 {len(all_phones)} 个型号")
    return all_phones


def step1_crawl_list_and_detail():
    logger.info("=" * 70)
    logger.info("步骤1：爬取手机列表和详情信息")
    logger.info("=" * 70)

    session = get_session()
    start_time = time.time()
    phones_crawled = 0
    skipped_count = 0

    # 增量模式：先全量扫描所有型号，与本地已有对比，仅爬取新增
    if INCREMENTAL_MODE:
        all_phones = _scan_all_models(session)
        existing_ids = _get_existing_phone_ids()
        new_phones = [p for p in all_phones if p['id'] not in existing_ids]

        logger.info(f"全量扫描完成：共 {len(all_phones)} 个型号，新增 {len(new_phones)} 个，已有 {len(all_phones) - len(new_phones)} 个")

        if not new_phones:
            logger.info("增量模式：未发现新增型号，无需爬取详情")
            progress['total_phones'] = 0
            save_progress()
            return

        # 仅对新增型号爬取详情
        for phone in new_phones:
            # 时间限制检查
            if MAX_TIME_PER_STEP > 0:
                elapsed = time.time() - start_time
                if elapsed >= MAX_TIME_PER_STEP:
                    logger.info(f"达到时间限制 ({MAX_TIME_PER_STEP}秒)，保存进度")
                    progress['total_phones'] = phones_crawled
                    save_progress()
                    if AUTO_MODE:
                        logger.info('未完成，等待下次继续')
                        sys.exit(10)
                    return

            # 手机数量限制检查
            if MAX_PHONES_PER_RUN > 0 and phones_crawled >= MAX_PHONES_PER_RUN:
                logger.info(f"达到手机数量限制 ({MAX_PHONES_PER_RUN}个)，保存进度")
                progress['total_phones'] = phones_crawled
                save_progress()
                if AUTO_MODE:
                    logger.info('达到数量上限，等待下次继续')
                    sys.exit(10)
                return

            phone_id = phone['id']
            detail = crawl_detail_page(session, phone_id)
            if detail:
                phone.update(detail)

                release_year = extract_release_year(phone)
                if not release_year:
                    params = crawl_param_page(session, phone_id)
                    if params:
                        phone.update(params)
                        release_year = extract_release_year(phone)

                if release_year and release_year >= MIN_YEAR:
                    if '处理器' not in phone:
                        params = crawl_param_page(session, phone_id)
                        if params:
                            phone.update(params)

                    # 字段标准化：将原始字段名映射为统一标准名
                    phone = normalize_phone_fields(phone)

                    # 从型号名称推导品牌
                    if not phone.get('品牌'):
                        phone['品牌'] = derive_brand_from_name(phone.get('型号', phone.get('name', '')))

                    phone_file = os.path.join(zol_json_dir, f"{phone_id}.json")
                    with open(phone_file, 'w', encoding='utf-8') as f:
                        json.dump(phone, f, ensure_ascii=False, indent=2)

                    phones_crawled += 1
                    progress.setdefault('crawled_phones', []).append(phone_id)
                    # 实时持久化：每成功爬取一个立即保存进度
                    save_progress()
                    logger.info(f"✓ 保存: {phone.get('name', phone.get('型号', '未知'))} ({release_year}年) - 共{phones_crawled}个")
                elif release_year:
                    logger.debug(f"跳过: {phone.get('name', phone.get('型号', '未知'))} ({release_year}年) - 不在近五年范围内")
                else:
                    logger.debug(f"跳过: {phone.get('name', phone.get('型号', '未知'))} - 无法获取发布年份")
            else:
                logger.warning(f"✗ 详情页爬取失败: {phone.get('name', phone.get('型号', '未知'))}")

        progress['total_phones'] = phones_crawled
        save_progress()
        logger.info(f"增量模式完成：新增 {phones_crawled} 个手机")
        return

    # 非增量模式：原有逻辑（全量爬取，支持断点续传）
    logger.info(f"从进度恢复: total_phones={phones_crawled}, crawled={len(progress.get('crawled_phones',[]))}, page={progress.get('current_page')}")

    page = progress.get('current_page', 1)
    phones_crawled = progress.get('total_phones', 0)

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

        if MAX_PAGES_PER_RUN > 0 and page > MAX_PAGES_PER_RUN:
            logger.info(f"达到页数限制 ({MAX_PAGES_PER_RUN}页)，保存进度")
            save_progress()
            return

        if MAX_PHONES_PER_RUN > 0 and phones_crawled >= MAX_PHONES_PER_RUN:
            logger.info(f"达到手机数量限制 ({MAX_PHONES_PER_RUN}个)，保存进度")
            save_progress()
            return

        phones = crawl_list_page(session, page)

        if not phones:
            logger.info("列表页为空，停止爬取")
            break

        for phone in phones:
            if MAX_TIME_PER_STEP > 0:
                elapsed = time.time() - start_time
                if elapsed >= MAX_TIME_PER_STEP:
                    logger.info(f"达到时间限制 ({MAX_TIME_PER_STEP}秒)，保存进度")
                    progress['current_page'] = page
                    progress['total_phones'] = phones_crawled
                    save_progress()
                    if AUTO_MODE:
                        logger.info('未完成，等待下次继续')
                        sys.exit(10)
                    return

            if MAX_PHONES_PER_RUN > 0 and phones_crawled >= MAX_PHONES_PER_RUN:
                logger.info(f"达到手机数量限制 ({MAX_PHONES_PER_RUN}个)，保存进度")
                progress['current_page'] = page
                progress['total_phones'] = phones_crawled
                save_progress()
                return

            phone_id = phone['id']

            if phone_id in progress.get('crawled_phones', []):
                continue

            detail = crawl_detail_page(session, phone_id)
            if detail:
                phone.update(detail)

                release_year = extract_release_year(phone)
                if not release_year:
                    params = crawl_param_page(session, phone_id)
                    if params:
                        phone.update(params)
                        release_year = extract_release_year(phone)

                if release_year and release_year >= MIN_YEAR:
                    if '处理器' not in phone:
                        params = crawl_param_page(session, phone_id)
                        if params:
                            phone.update(params)

                    # 字段标准化：将原始字段名映射为统一标准名
                    phone = normalize_phone_fields(phone)

                    # 从型号名称推导品牌
                    if not phone.get('品牌'):
                        phone['品牌'] = derive_brand_from_name(phone.get('型号', phone.get('name', '')))

                    phone_file = os.path.join(zol_json_dir, f"{phone_id}.json")
                    with open(phone_file, 'w', encoding='utf-8') as f:
                        json.dump(phone, f, ensure_ascii=False, indent=2)

                    phones_crawled += 1
                    progress['crawled_phones'].append(phone_id)
                    # 实时持久化
                    save_progress()
                    logger.info(f"✓ 保存: {phone.get('name', phone.get('型号', '未知'))} ({release_year}年) - 共{phones_crawled}个")
                elif release_year:
                    logger.debug(f"跳过: {phone.get('name', phone.get('型号', '未知'))} ({release_year}年) - 不在近五年范围内")
                else:
                    logger.debug(f"跳过: {phone.get('name', phone.get('型号', '未知'))} - 无法获取发布年份")
            else:
                logger.warning(f"✗ 详情页爬取失败: {phone.get('name', phone.get('型号', '未知'))}")

        progress['crawled_pages'].append(page)
        progress['current_page'] = page + 1
        progress['total_phones'] = phones_crawled
        save_progress()

        page += 1

    logger.info(f"步骤1完成！共爬取 {phones_crawled} 个手机")


def find_latest(pattern):
    """查找最新匹配文件"""
    files = glob.glob(os.path.join(working_dir, pattern))
    if not files:
        files = glob.glob(os.path.join(working_dir, '**', pattern), recursive=True)
    if not files:
        return None
    data_files = [f for f in files if 'progress' not in f and 'manifest' not in f]
    if not data_files:
        data_files = files
    return max(data_files, key=os.path.getmtime)


def load(path):
    if not path or not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def step2_parse_and_merge():
    logger.info("=" * 70)
    logger.info("步骤2：解析和合并数据")
    logger.info("=" * 70)
    
    all_phones = []
    for filename in os.listdir(zol_json_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(zol_json_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    phone_data = json.load(f)
                    # 标准化字段名
                    phone_data = normalize_phone_fields(phone_data)
                    all_phones.append(phone_data)
            except Exception as e:
                logger.error(f"读取文件失败: {filepath} - {e}")

    logger.info(f"总共读取 {len(all_phones)} 个手机数据")

    if not all_phones:
        prev_file = find_latest("zol_phones_*.json")
        if prev_file:
            all_phones = load(prev_file)
            logger.info(f"zol/json/ 为空，复用上次数据: {os.path.basename(prev_file)} ({len(all_phones)} 条)")
    
    if not all_phones:
        progress_file = os.path.join(zol_dir, 'progress.json')
        if os.path.exists(progress_file):
            with open(progress_file, 'r', encoding='utf-8') as f:
                progress = json.load(f)
            if progress.get('processed_phones') or progress.get('crawled_phones'):
                logger.warning("有进度记录但无数据文件——状态不一致，重置进度让下次全量爬取")
                progress['current_page'] = 1
                progress['total_phones'] = 0
                progress['processed_phones'] = []
                progress['crawled_phones'] = []
                with open(progress_file, 'w', encoding='utf-8') as f:
                    json.dump(progress, f, ensure_ascii=False, indent=2)
        logger.warning("没有任何手机数据（既无历史也无新增），将输出空文件")
    
    all_phones.sort(key=lambda x: x.get('国内发布时间', ''), reverse=True)
    
    today = date.today().strftime("%Y%m%d")
    output_file = os.path.join(working_dir, f"zol_phones_{today}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_phones, f, ensure_ascii=False, indent=2)
    
    logger.info(f"合并数据已保存到: {output_file}")
    
    csv_file = os.path.join(working_dir, f"zol_phones_{today}.csv")
    if all_phones:
        all_keys = set()
        for phone in all_phones:
            all_keys.update(phone.keys())
        
        fixed_keys = ['id', 'name', 'source', '国内发布时间', '上市日期', '电商报价']
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
    for filename in os.listdir(zol_json_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(zol_json_dir, filename)
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


def main():
    logger.info("中关村在线手机参数爬虫")
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
