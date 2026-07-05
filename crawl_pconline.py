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
from typing import List, Dict, Optional, Tuple
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
    '屏幕大小': '屏幕',
    '屏幕类型': '屏幕',
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
    '电池类型': '电池',
    'RAM容量': '内存',
    '运行内存': '内存',
    '运行内存(RAM)': '内存',
    '内存': '内存',
    '运存类型': '内存',
    'ROM容量': '存储',
    '机身存储': '存储',
    '机身容量': '存储',
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
        # 如果新键已存在，合并值（取非空的）
        if new_key in normalized and not normalized[new_key] and value:
            normalized[new_key] = value
        elif new_key not in normalized:
            normalized[new_key] = value
        elif value and normalized[new_key]:
            # 两个都有值，保留较长的
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

PCONLINE_BRAND_MAP = {
    'apple': '苹果', 'bubugao': '步步高', 'oppo': 'OPPO', 'honor': '荣耀',
    'miui': '小米', 'redmi': '红米', 'oneplus': '一加', 'realme': '真我',
    'iqoo': 'iQOO', 'samsung': '三星', 'motorola': '摩托罗拉', 'nubia': '努比亚',
}

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

parser = argparse.ArgumentParser(description='太平洋电脑网手机爬虫')
parser.add_argument('--step', type=int, choices=[1, 2, 3], help='运行指定步骤')
parser.add_argument('--time-limit', type=int, default=0, help='每步最大运行时间(秒)，0表示不限制')
parser.add_argument('--max-phones', type=int, default=0, help='最多爬取手机数，0表示不限制')
parser.add_argument('--auto', action='store_true', help='全自动模式：未完成则exit code 10')
parser.add_argument('--restart', action='store_true', help='重置进度，从头开始')
parser.add_argument('--incremental', action='store_true', help='增量模式：只爬取新增手机')
parser.add_argument('--debug-limit', type=int, default=0, help='调试模式限制爬取数量（配合 --incremental 使用）')
args = parser.parse_args()

MAX_TIME_PER_STEP = args.time_limit
MAX_PHONES_PER_RUN = args.max_phones
AUTO_MODE = args.auto
INCREMENTAL_MODE = args.incremental

# 调试模式：强制开启增量扫描模式，并限制爬取数量
if args.debug_limit > 0:
    INCREMENTAL_MODE = True
    MAX_PHONES_PER_RUN = args.debug_limit
    logger.info(f"调试模式：限制爬取 {args.debug_limit} 个手机，启用增量扫描模式")

working_dir = os.path.dirname(os.path.abspath(__file__))
pconline_dir = os.path.join(working_dir, 'pconline')
pconline_json_dir = os.path.join(pconline_dir, 'json')
pconline_exception_dir = os.path.join(pconline_dir, 'exception')
data_dir = os.path.join(working_dir, 'data')
os.makedirs(data_dir, exist_ok=True)

for d in [pconline_dir, pconline_json_dir, pconline_exception_dir]:
    if not os.path.exists(d):
        os.makedirs(d)

progress_file = os.path.join(pconline_dir, 'progress.json')
if os.path.exists(progress_file) and not args.restart:
    with open(progress_file, 'r', encoding='utf-8') as f:
        progress = json.load(f)
    # 向后兼容：旧进度文件可能缺少新字段
    if 'current_brand_index' not in progress:
        progress['current_brand_index'] = 0
    if 'current_page' not in progress:
        progress['current_page'] = 1
    if 'processed_phones' not in progress:
        progress['processed_phones'] = list(progress.get('crawled_phones', []))
    if 'skipped_phones' not in progress:
        progress['skipped_phones'] = {}
    logger.info('从上次进度继续（使用 --restart 可重新开始）')
else:
    progress = {
        'crawled_phones': [],
        'processed_phones': [],
        'skipped_phones': {},
        'total_phones': 0,
        'current_brand_index': 0,
        'current_page': 1
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
    'Referer': 'https://product.pconline.com.cn/'
}

BASE_URL = "https://product.pconline.com.cn"

# 品牌列表（作为 crawl_brand_list 解析失败时的兜底）
FALLBACK_BRANDS = [
    'apple', 'bubugao', 'oppo', 'honor', 'miui', 'redmi',
    'oneplus', 'realme', 'iqoo', 'samsung', 'motorola', 'nubia'
]

# PHONE_BRAND_HEAT_ORDER 保留作为兜底；正常运行时不使用，爬虫会通过
# crawl_brand_heat() 从 PConline 各品牌子页动态获取型号数排序。
PHONE_BRAND_HEAT_ORDER = [
    'apple', 'oppo', 'honor', 'vivo', 'miui', 'redmi',
    'huawei', 'samsung', 'iqoo', 'realme', 'oneplus', 'bubugao',
    'motorola', 'nubia', 'meizu', 'zte', 'lenovo',
    'sony', 'google', 'nokia', 'nothing', 'tecno',
]


def crawl_brand_heat(session: requests.Session, brands: List[str], max_brands: int = 30) -> Dict[str, int]:
    """从 PConline 各品牌子页动态抓取型号总数，作为品牌热度代理。
    每个 mobile/{brand}/ 页包含"共 X 件"文本。失败时使用 PHONE_BRAND_HEAT_ORDER兜底。
    """
    heat: Dict[str, int] = {}
    fall_back = {b.strip().lower(): idx for idx, b in enumerate(PHONE_BRAND_HEAT_ORDER)}
    for brand in brands[:max_brands]:
        try:
            url = f'https://product.pconline.com.cn/mobile/{brand}/'
            human_delay(f"PConline 品牌热度探测 {brand}")
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                # 用兜底位次
                idx = fall_back.get(brand.lower(), 9999)
                heat[brand] = -idx
                continue
            resp.encoding = 'gbk'
            m = re.search(r'共\s*(\d+)\s*[件个款台条]', resp.text)
            if m:
                heat[brand] = int(m.group(1))
            else:
                idx = fall_back.get(brand.lower(), 9999)
                heat[brand] = -idx
        except Exception:
            idx = fall_back.get(brand.lower(), 9999)
            heat[brand] = -idx
    return heat


def sort_brands_by_heat(brands: List[str], session: Optional[requests.Session] = None) -> List[str]:
    """按品牌销量热度排序，热门品牌优先爬取。
    优先使用 crawl_brand_heat() 动态获取；若 session 为 None 则使用硬编码兜底。
    """
    if session is None:
        session = get_session()
    heat = crawl_brand_heat(session, brands)
    if not heat:
        heat_map = {b.strip().lower(): idx for idx, b in enumerate(PHONE_BRAND_HEAT_ORDER)}
        sorted_brands = sorted(brands, key=lambda b: heat_map.get(b.strip().lower(), 999))
        logger.info(f"品牌按热度(兜底排序)重排: {sorted_brands[:10]}...")
        return sorted_brands
    sorted_brands = sorted(brands, key=lambda b: -heat.get(b, 0))
    logger.info(f"品牌按动态热度重排: {sorted_brands[:8]}...（共 {len(sorted_brands)} 个品牌的型号数为 {sum(heat.values())}）")
    return sorted_brands


def save_progress():
    with open(progress_file, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def mark_processed(phone_id: str, reason: str = ''):
    processed = progress.setdefault('processed_phones', [])
    if phone_id not in processed:
        processed.append(phone_id)
    if reason:
        progress.setdefault('skipped_phones', {})[phone_id] = reason


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


def crawl_brand_list(session: requests.Session) -> List[str]:
    """从品牌目录页提取所有品牌子目录"""
    url = "https://product.pconline.com.cn/mobile/"
    logger.info(f"爬取品牌目录页: {url}")
    
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.encoding = 'gbk'
        
        if resp.status_code != 200:
            logger.warning(f"品牌目录页请求失败 (状态码: {resp.status_code})")
            return FALLBACK_BRANDS
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        links = soup.find_all('a', href=re.compile(r'/mobile/\w+/'))
        brands = []
        seen = set()
        EXCLUDE_BRANDS = {'index', 'list', 'help', 'news', 'search', 'mobile', 'price', 'brand', 'series'}
        for link in links:
            href = link.get('href', '')
            brand_match = re.search(r'/mobile/(\w+)/', href)
            if brand_match:
                brand = brand_match.group(1)
                # 过滤掉非品牌项：系列页、分类代码(c数字/p数字)、纯数字
                if (brand not in seen and brand not in EXCLUDE_BRANDS 
                    and len(brand) >= 2
                    and not re.match(r'^[cp]\d+$', brand)  # 分类代码如 c20551, p167
                    and not brand.isdigit()):  # 纯数字
                    brands.append(brand)
                    seen.add(brand)
        
        if brands:
            logger.info(f"从页面提取 {len(brands)} 个品牌: {brands}")
            return brands
        else:
            logger.warning("页面未提取到品牌，使用兜底品牌列表")
            return FALLBACK_BRANDS
        
    except Exception as e:
        logger.error(f"爬取品牌目录异常: {e}")
        return FALLBACK_BRANDS


def crawl_list_page(session: requests.Session, brand: str, page: int = 1) -> List[Dict]:
    """爬取指定品牌的分页列表页"""
    if page == 1:
        url = f"https://product.pconline.com.cn/mobile/{brand}/"
    else:
        offset = (page - 1) * 25
        url = f"https://product.pconline.com.cn/mobile/{brand}/{offset}s1.shtml"
    
    logger.info(f"爬取列表页 (品牌={brand}, 第{page}页): {url}")
    
    try:
        human_delay(f"列表页请求 [品牌={brand}, 页={page}]")
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.encoding = 'gbk'
        
        if resp.status_code != 200:
            logger.warning(f"请求失败: {url} (状态码: {resp.status_code})")
            return []
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        phones = []
        
        links = soup.find_all('a', href=re.compile(r'//product\.pconline\.com\.cn/mobile/\w+/\d+\.html'))
        for link in links:
            href = link.get('href', '')
            name = link.get_text(strip=True)
            if href and name and len(name) > 2:
                phone_id_match = re.search(r'/(\d+)\.html', href)
                brand_match = re.search(r'/mobile/(\w+)/\d+\.html', href)
                if phone_id_match:
                    phone_id = phone_id_match.group(1)
                    brand_name = brand_match.group(1) if brand_match else brand
                    # 跳过系列概览页（不是真正的手机详情页）
                    if brand_name == 'series':
                        continue
                    phones.append({
                        'id': phone_id,
                        'name': name,
                        'brand': brand_name,
                        'url': f"https:{href}" if href.startswith('//') else href,
                        'source': '太平洋电脑网'
                    })
        
        logger.info(f"品牌={brand} 第{page}页 找到 {len(phones)} 个手机")
        return phones
        
    except Exception as e:
        logger.error(f"爬取列表页异常: {e}")
        return []


def crawl_detail_page(session: requests.Session, phone_id: str, brand: str = '') -> Optional[Dict]:
    if brand:
        url = f"https://product.pconline.com.cn/mobile/{brand}/{phone_id}.html"
    else:
        url = f"https://product.pconline.com.cn/mobile/{phone_id}.html"
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
            detail['param_url'] = param_href if param_href.startswith('http') else f"https:{param_href}" if param_href.startswith('//') else f"https://product.pconline.com.cn{param_href}"
        
        info_div = soup.find('div', class_='info')
        if info_div:
            items = info_div.find_all('li')
            for item in items:
                text = item.get_text(strip=True)
                if '：' in text:
                    key, value = text.split('：', 1)
                    if key and value:
                        detail[key.strip()] = value.strip()
        
        return detail
        
    except Exception as e:
        logger.error(f"爬取详情页异常: {e}")
        return None


def crawl_param_page(session: requests.Session, phone_id: str, brand: str = '') -> Optional[Dict]:
    if brand:
        url = f"https://product.pconline.com.cn/mobile/{brand}/{phone_id}_detail.html"
    else:
        url = f"https://product.pconline.com.cn/mobile/{phone_id}_detail.html"
    logger.info(f"爬取参数页: {url}")
    
    try:
        human_delay("参数页请求")
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.encoding = 'gbk'
        
        if resp.status_code != 200:
            logger.warning(f"请求失败: {url} (状态码: {resp.status_code})")
            return None
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        params = {}
        
        tables = soup.find_all('table', class_='dtparams-table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                th = row.find('th')
                td = row.find('td')
                if th and td:
                    key = th.get_text(strip=True)
                    value = td.get_text(strip=True)
                    if key and value:
                        key = re.sub(r'\s+', ' ', key).strip()
                        params[key] = value
        
        if not params:
            tables = soup.find_all('table')
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
    time_fields = ['上市时间', '发布时间', '发布日期', '上市日期']
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
    if not os.path.exists(pconline_json_dir):
        return existing
    for filename in os.listdir(pconline_json_dir):
        if filename.endswith('.json'):
            phone_id = filename.replace('.json', '')
            existing.add(phone_id)
    return existing


def _scan_all_models(session: requests.Session, start_time: float) -> Tuple[List[Dict], bool, int, int]:
    """全量扫描所有品牌的所有型号（仅收集基础信息，不爬详情）"""
    logger.info("=" * 70)
    logger.info("增量扫描模式：全量扫描所有品牌型号...")
    logger.info("=" * 70)

    brands = crawl_brand_list(session)
    if MAX_TIME_PER_STEP > 0 or MAX_PHONES_PER_RUN > 0:
        heat_map = {b.strip().lower(): idx for idx, b in enumerate(PHONE_BRAND_HEAT_ORDER)}
        brands = sorted(brands, key=lambda b: heat_map.get(b.strip().lower(), 999))
        logger.info(f"预算扫描模式：跳过动态品牌热度探测，使用兜底热度排序: {brands[:10]}...")
    else:
        brands = sort_brands_by_heat(brands, session)
    logger.info(f"品牌列表 ({len(brands)}): {brands}")

    all_phones = []
    truncated = False
    next_brand_index = len(brands)
    next_page = 1
    current_brand_idx = progress.get('current_brand_index', 0)
    current_page = progress.get('current_page', 1)
    # 扫描候选保留 3 倍余量，避免已存在机型过滤后拿不到足够新增详情。
    scan_limit = MAX_PHONES_PER_RUN * 3 if MAX_PHONES_PER_RUN > 0 else 0

    for bi in range(current_brand_idx, len(brands)):
        brand = brands[bi]
        page = current_page if bi == current_brand_idx else 1
        while True:
            if MAX_TIME_PER_STEP > 0 and time.time() - start_time >= MAX_TIME_PER_STEP:
                logger.info(f"增量型号扫描达到时间限制 ({MAX_TIME_PER_STEP}秒)，保存扫描游标")
                truncated = True
                next_brand_index = bi
                next_page = page
                break
            if scan_limit > 0 and len(all_phones) >= scan_limit:
                logger.info(f"达到增量扫描候选上限 ({scan_limit}个型号)，保存扫描游标")
                truncated = True
                next_brand_index = bi
                next_page = page
                break

            phones = crawl_list_page(session, brand, page)
            if not phones:
                next_brand_index = bi + 1
                next_page = 1
                break
            all_phones.extend(phones)
            if len(phones) < 25:
                next_brand_index = bi + 1
                next_page = 1
                break
            page += 1

            if MAX_TIME_PER_STEP > 0 and time.time() - start_time >= MAX_TIME_PER_STEP:
                logger.info(f"增量型号扫描达到时间限制 ({MAX_TIME_PER_STEP}秒)，保存扫描游标")
                truncated = True
                next_brand_index = bi
                next_page = page
                break
            if scan_limit > 0 and len(all_phones) >= scan_limit:
                logger.info(f"达到增量扫描候选上限 ({scan_limit}个型号)，保存扫描游标")
                truncated = True
                next_brand_index = bi
                next_page = page
                break
        if truncated:
            break
    logger.info(f"全量扫描完成：共 {len(all_phones)} 个型号")
    return all_phones, truncated, next_brand_index, next_page


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
        all_phones, scan_truncated, next_brand_index, next_page = _scan_all_models(session, start_time)
        existing_ids = _get_existing_phone_ids()
        new_phones = [p for p in all_phones if p['id'] not in existing_ids]

        logger.info(f"全量扫描完成：共 {len(all_phones)} 个型号，新增 {len(new_phones)} 个，已有 {len(all_phones) - len(new_phones)} 个")

        if not new_phones:
            progress['current_brand_index'] = next_brand_index
            progress['current_page'] = next_page
            logger.info("增量模式：未发现新增型号，无需爬取详情")
            progress['total_phones'] = 0
            save_progress()
            if scan_truncated and AUTO_MODE:
                logger.info('增量扫描未完成，等待下次继续扫描')
                sys.exit(10)
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
            detail = crawl_detail_page(session, phone_id, phone.get('brand', ''))
            if detail:
                phone.update(detail)

                release_year = extract_release_year(phone)
                if not release_year:
                    params = crawl_param_page(session, phone_id, phone.get('brand', ''))
                    if params:
                        phone.update(params)
                        release_year = extract_release_year(phone)

                if release_year and release_year >= MIN_YEAR:
                    if '处理器' not in phone:
                        params = crawl_param_page(session, phone_id, phone.get('brand', ''))
                        if params:
                            phone.update(params)

                    # 字段标准化：将原始字段名映射为统一标准名
                    phone = normalize_phone_fields(phone)

                    # 从型号名推导品牌（优先使用URL brand的中文翻译）
                    if not phone.get('品牌'):
                        url_brand = phone.get('brand', '')
                        if url_brand and url_brand in PCONLINE_BRAND_MAP:
                            phone['品牌'] = PCONLINE_BRAND_MAP[url_brand]
                        else:
                            phone['品牌'] = derive_brand_from_name(phone.get('型号', phone.get('name', '')))

                    phone_file = os.path.join(pconline_json_dir, f"{phone_id}.json")
                    with open(phone_file, 'w', encoding='utf-8') as f:
                        json.dump(phone, f, ensure_ascii=False, indent=2)

                    phones_crawled += 1
                    progress.setdefault('crawled_phones', []).append(phone_id)
                    mark_processed(phone_id)
                    # 实时持久化：每成功爬取一个立即保存进度
                    save_progress()
                    logger.info(f"✓ 保存: {phone.get('name', phone.get('型号', '未知'))} ({release_year}年) - 共{phones_crawled}个")
                elif release_year:
                    mark_processed(phone_id, f"year:{release_year}")
                    logger.info(f"跳过: {phone.get('name', phone.get('型号', '未知'))} ({release_year}年) - 不在近五年范围内")
                else:
                    mark_processed(phone_id, "no_release_year")
                    logger.info(f"跳过: {phone.get('name', phone.get('型号', '未知'))} - 无法获取发布年份")
            else:
                logger.warning(f"✗ 详情页爬取失败: {phone.get('name', phone.get('型号', '未知'))}")

        progress['total_phones'] = phones_crawled
        progress['current_brand_index'] = next_brand_index
        progress['current_page'] = next_page
        save_progress()
        if scan_truncated:
            logger.info("增量扫描未完成，本次已处理当前扫描片段，等待下次继续")
            if AUTO_MODE:
                sys.exit(10)
            return
        logger.info(f"增量模式完成：新增 {phones_crawled} 个手机")
        return

    # 非增量模式：原有逻辑（全量爬取，支持断点续传）
    logger.info(f"从进度恢复: total_phones={phones_crawled}, processed={len(progress.get('processed_phones',[]))}, crawled={len(progress.get('crawled_phones',[]))}, brand_idx={progress.get('current_brand_index')}")

    brands = crawl_brand_list(session)
    brands = sort_brands_by_heat(brands)
    logger.info(f"品牌列表 ({len(brands)}): {brands}")

    current_brand_idx = progress.get('current_brand_index', 0)
    current_page = progress.get('current_page', 1)

    for bi in range(current_brand_idx, len(brands)):
        brand = brands[bi]
        page = current_page if bi == current_brand_idx else 1
        progress['current_brand_index'] = bi
        progress['current_page'] = page

        while True:
            # 时间限制检查
            if MAX_TIME_PER_STEP > 0:
                elapsed = time.time() - start_time
                if elapsed >= MAX_TIME_PER_STEP:
                    logger.info(f"达到时间限制 ({MAX_TIME_PER_STEP}秒)，保存进度")
                    progress['total_phones'] = phones_crawled
                    progress['current_page'] = page
                    save_progress()
                    if AUTO_MODE:
                        logger.info('未完成，等待下次继续')
                        sys.exit(10)
                    return

            # 手机数量限制检查
            if MAX_PHONES_PER_RUN > 0 and phones_crawled >= MAX_PHONES_PER_RUN:
                logger.info(f"达到手机数量限制 ({MAX_PHONES_PER_RUN}个)，保存进度")
                progress['total_phones'] = phones_crawled
                progress['current_page'] = page
                save_progress()
                if AUTO_MODE:
                    logger.info('达到数量上限，等待下次继续')
                    sys.exit(10)
                return

            phones = crawl_list_page(session, brand, page)

            if not phones:
                progress['current_brand_index'] = bi + 1
                progress['current_page'] = 1
                progress['total_phones'] = phones_crawled
                save_progress()
                break

            progress['current_page'] = page

            for phone in phones:
                if MAX_TIME_PER_STEP > 0:
                    elapsed = time.time() - start_time
                    if elapsed >= MAX_TIME_PER_STEP:
                        logger.info(f"达到时间限制 ({MAX_TIME_PER_STEP}秒)，保存进度")
                        progress['total_phones'] = phones_crawled
                        progress['current_page'] = page
                        save_progress()
                        if AUTO_MODE:
                            logger.info('未完成，等待下次继续')
                            sys.exit(10)
                        return

                if MAX_PHONES_PER_RUN > 0 and phones_crawled >= MAX_PHONES_PER_RUN:
                    logger.info(f"达到手机数量限制 ({MAX_PHONES_PER_RUN}个)，保存进度")
                    progress['total_phones'] = phones_crawled
                    progress['current_page'] = page
                    save_progress()
                    if AUTO_MODE:
                        logger.info('达到数量上限，等待下次继续')
                        sys.exit(10)
                    return

                phone_id = phone['id']

                if phone_id in progress.get('processed_phones', []) or phone_id in progress.get('crawled_phones', []):
                    continue

                detail = crawl_detail_page(session, phone_id, phone.get('brand', ''))
                if detail:
                    phone.update(detail)

                    release_year = extract_release_year(phone)
                    if not release_year:
                        params = crawl_param_page(session, phone_id, phone.get('brand', ''))
                        if params:
                            phone.update(params)
                            release_year = extract_release_year(phone)

                    if release_year and release_year >= MIN_YEAR:
                        if '处理器' not in phone:
                            params = crawl_param_page(session, phone_id, phone.get('brand', ''))
                            if params:
                                phone.update(params)

                        # 字段标准化：将原始字段名映射为统一标准名
                        phone = normalize_phone_fields(phone)

                        # 从型号名推导品牌（优先使用URL brand的中文翻译）
                        if not phone.get('品牌'):
                            url_brand = phone.get('brand', '')
                            if url_brand and url_brand in PCONLINE_BRAND_MAP:
                                phone['品牌'] = PCONLINE_BRAND_MAP[url_brand]
                            else:
                                phone['品牌'] = derive_brand_from_name(phone.get('型号', phone.get('name', '')))

                        phone_file = os.path.join(pconline_json_dir, f"{phone_id}.json")
                        with open(phone_file, 'w', encoding='utf-8') as f:
                            json.dump(phone, f, ensure_ascii=False, indent=2)

                        phones_crawled += 1
                        progress['crawled_phones'].append(phone_id)
                        mark_processed(phone_id)
                        # 实时持久化
                        save_progress()
                        logger.info(f"✓ 保存: {phone.get('name', phone.get('型号', '未知'))} ({release_year}年) - 共{phones_crawled}个")
                    elif release_year:
                        mark_processed(phone_id, f"year:{release_year}")
                        logger.info(f"跳过: {phone.get('name', phone.get('型号', '未知'))} ({release_year}年) - 不在近五年范围内")
                    else:
                        mark_processed(phone_id, "no_release_year")
                        logger.info(f"跳过: {phone.get('name', phone.get('型号', '未知'))} - 无法获取发布年份")
                else:
                    logger.warning(f"✗ 详情页爬取失败: {phone.get('name', phone.get('型号', '未知'))}")

            progress['total_phones'] = phones_crawled
            progress['current_brand_index'] = bi
            progress['current_page'] = page + 1
            save_progress()

            if len(phones) < 25:
                progress['current_brand_index'] = bi + 1
                progress['current_page'] = 1
                progress['total_phones'] = phones_crawled
                save_progress()
                break
            page += 1

    progress['total_phones'] = phones_crawled
    save_progress()
    logger.info(f"步骤1完成！共爬取 {phones_crawled} 个手机")


def find_latest(pattern):
    """查找最新匹配文件"""
    files = glob.glob(os.path.join(data_dir, pattern))
    if not files:
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
    for filename in os.listdir(pconline_json_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(pconline_json_dir, filename)
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
        prev_file = find_latest("pconline_phones_*.json")
        if prev_file:
            all_phones = load(prev_file)
            logger.info(f"pconline/json/ 为空，复用上次数据: {os.path.basename(prev_file)} ({len(all_phones)} 条)")
    
    if not all_phones:
        progress_file = os.path.join(pconline_dir, 'progress.json')
        if os.path.exists(progress_file):
            with open(progress_file, 'r', encoding='utf-8') as f:
                progress = json.load(f)
            if progress.get('processed_phones') or progress.get('crawled_phones'):
                logger.warning("有进度记录但无数据文件——状态不一致，重置进度让下次全量爬取")
                progress['current_brand_index'] = 0
                progress['current_page'] = 1
                progress['total_phones'] = 0
                progress['processed_phones'] = []
                progress['crawled_phones'] = []
                with open(progress_file, 'w', encoding='utf-8') as f:
                    json.dump(progress, f, ensure_ascii=False, indent=2)
        logger.warning("没有任何手机数据（既无历史也无新增），将输出空文件")
    
    all_phones.sort(key=lambda x: x.get('上市时间', ''), reverse=True)
    
    today = date.today().strftime("%Y%m%d")
    output_file = os.path.join(data_dir, f"pconline_phones_{today}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_phones, f, ensure_ascii=False, indent=2)
    
    logger.info(f"合并数据已保存到: {output_file}")
    
    csv_file = os.path.join(data_dir, f"pconline_phones_{today}.csv")
    if all_phones:
        all_keys = set()
        for phone in all_phones:
            all_keys.update(phone.keys())
        
        fixed_keys = ['id', 'name', 'source', '上市时间', '发布时间', '价格']
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
    
    logger.info(f"爬取手机数: {total_phones}")
    
    brand_count = {}
    for filename in os.listdir(pconline_json_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(pconline_json_dir, filename)
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
    logger.info("太平洋电脑网手机参数爬虫")
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
