#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import random
import re
import csv
import argparse
from datetime import datetime, date
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup

parser = argparse.ArgumentParser(description='太平洋电脑网手机爬虫')
parser.add_argument('--step', type=int, choices=[1, 2, 3], help='运行指定步骤')
parser.add_argument('--time-limit', type=int, default=0, help='每步最大运行时间(秒)，0表示不限制')
parser.add_argument('--max-pages', type=int, default=0, help='第一步最多爬取页数，0表示不限制')
parser.add_argument('--auto', action='store_true', help='全自动模式：未完成则exit code 10')
parser.add_argument('--restart', action='store_true', help='重置进度，从头开始')
args = parser.parse_args()

MAX_TIME_PER_STEP = args.time_limit
MAX_PAGES_PER_RUN = args.max_pages
AUTO_MODE = args.auto

working_dir = os.path.dirname(os.path.abspath(__file__))
pconline_dir = os.path.join(working_dir, 'pconline')
pconline_json_dir = os.path.join(pconline_dir, 'json')
pconline_exception_dir = os.path.join(pconline_dir, 'exception')

for d in [pconline_dir, pconline_json_dir, pconline_exception_dir]:
    if not os.path.exists(d):
        os.makedirs(d)

progress_file = os.path.join(pconline_dir, 'progress.json')
if os.path.exists(progress_file) and not args.restart:
    with open(progress_file, 'r', encoding='utf-8') as f:
        progress = json.load(f)
    print('从上次进度继续（使用 --restart 可重新开始）')
else:
    progress = {
        'crawled_pages': [],
        'crawled_phones': [],
        'current_page': 1,
        'total_phones': 0
    }
    print('初始化新进度')

CURRENT_YEAR = 2026
MIN_YEAR = 2021
REQUEST_DELAY_MIN = 2.0
REQUEST_DELAY_MAX = 3.0
REQUEST_TIMEOUT = 15

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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


def save_progress():
    with open(progress_file, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def delay_request():
    delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
    time.sleep(delay)


def get_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def crawl_list_page(session: requests.Session, page: int) -> List[Dict]:
    url = "https://product.pconline.com.cn/mobile/"
    print(f"爬取列表页: {url}")
    
    try:
        delay_request()
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.encoding = 'utf-8'
        
        if resp.status_code != 200:
            print(f"请求失败: {url} (状态码: {resp.status_code})")
            return []
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        phones = []
        
        links = soup.find_all('a', href=re.compile(r'//product\.pconline\.com\.cn/mobile/\w+/\d+\.html'))
        for link in links:
            href = link.get('href', '')
            name = link.get_text(strip=True)
            if href and name and len(name) > 2:
                phone_id_match = re.search(r'/(\d+)\.html', href)
                if phone_id_match:
                    phone_id = phone_id_match.group(1)
                    phones.append({
                        'id': phone_id,
                        'name': name,
                        'url': f"https:{href}" if href.startswith('//') else href,
                        'source': '太平洋电脑网'
                    })
        
        print(f"找到 {len(phones)} 个手机")
        return phones
        
    except Exception as e:
        print(f"爬取列表页异常: {e}")
        return []


def crawl_detail_page(session: requests.Session, phone_id: str) -> Optional[Dict]:
    url = f"https://product.pconline.com.cn/mobile/{phone_id}.html"
    print(f"爬取详情页: {url}")
    
    try:
        delay_request()
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.encoding = 'utf-8'
        
        if resp.status_code != 200:
            print(f"请求失败: {url} (状态码: {resp.status_code})")
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
        print(f"爬取详情页异常: {e}")
        return None


def crawl_param_page(session: requests.Session, phone_id: str) -> Optional[Dict]:
    url = f"https://product.pconline.com.cn/mobile/{phone_id}_param.shtml"
    print(f"爬取参数页: {url}")
    
    try:
        delay_request()
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.encoding = 'utf-8'
        
        if resp.status_code != 200:
            print(f"请求失败: {url} (状态码: {resp.status_code})")
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
        
        if not params:
            params_div = soup.find('div', class_='params')
            if params_div:
                items = params_div.find_all('li')
                for item in items:
                    text = item.get_text(strip=True)
                    if '：' in text:
                        key, value = text.split('：', 1)
                        if key and value:
                            params[key.strip()] = value.strip()
        
        print(f"提取 {len(params)} 个参数")
        return params
        
    except Exception as e:
        print(f"爬取参数页异常: {e}")
        return None


def extract_release_year(detail: Dict) -> Optional[int]:
    time_fields = ['上市时间', '发布时间', '发布日期', '上市日期']
    for field in time_fields:
        if field in detail:
            time_str = detail[field]
            year_match = re.search(r'(\d{4})', time_str)
            if year_match:
                return int(year_match.group(1))
    
    return None


def step1_crawl_list_and_detail():
    print("\n" + "="*70)
    print("步骤1：爬取手机列表和详情信息")
    print("="*70)
    
    session = get_session()
    start_time = time.time()
    page = progress.get('current_page', 1)
    phones_crawled = progress.get('total_phones', 0)
    
    while True:
        if MAX_TIME_PER_STEP > 0:
            elapsed = time.time() - start_time
            if elapsed >= MAX_TIME_PER_STEP:
                print(f"达到时间限制 ({MAX_TIME_PER_STEP}秒)，保存进度")
                save_progress()
                if AUTO_MODE:
                    sys.exit(10)
                return
        
        if MAX_PAGES_PER_RUN > 0 and page > MAX_PAGES_PER_RUN:
            print(f"达到页数限制 ({MAX_PAGES_PER_RUN}页)，保存进度")
            save_progress()
            return
        
        phones = crawl_list_page(session, page)
        
        if not phones:
            print("列表页为空，停止爬取")
            break
        
        for phone in phones:
            if MAX_TIME_PER_STEP > 0:
                elapsed = time.time() - start_time
                if elapsed >= MAX_TIME_PER_STEP:
                    print(f"达到时间限制 ({MAX_TIME_PER_STEP}秒)，保存进度")
                    progress['current_page'] = page
                    progress['total_phones'] = phones_crawled
                    save_progress()
                    if AUTO_MODE:
                        sys.exit(10)
                    return
            
            phone_id = phone['id']
            
            if phone_id in progress.get('crawled_phones', []):
                print(f"跳过已爬取: {phone['name']} (ID: {phone_id})")
                continue
            
            detail = crawl_detail_page(session, phone_id)
            if detail:
                phone.update(detail)
                
                release_year = extract_release_year(phone)
                if release_year and release_year >= MIN_YEAR:
                    params = crawl_param_page(session, phone_id)
                    if params:
                        phone.update(params)
                    
                    phone_file = os.path.join(pconline_json_dir, f"{phone_id}.json")
                    with open(phone_file, 'w', encoding='utf-8') as f:
                        json.dump(phone, f, ensure_ascii=False, indent=2)
                    
                    phones_crawled += 1
                    progress['crawled_phones'].append(phone_id)
                    print(f"✓ 保存: {phone['name']} ({release_year}年) - 共{phones_crawled}个")
                else:
                    print(f"跳过: {phone['name']} ({release_year}年) - 不在近五年范围内")
            else:
                print(f"✗ 详情页爬取失败: {phone['name']}")
        
        progress['crawled_pages'].append(page)
        progress['current_page'] = page + 1
        progress['total_phones'] = phones_crawled
        save_progress()
        
        page += 1
    
    print(f"\n步骤1完成！共爬取 {phones_crawled} 个手机")


def step2_parse_and_merge():
    print("\n" + "="*70)
    print("步骤2：解析和合并数据")
    print("="*70)
    
    all_phones = []
    for filename in os.listdir(pconline_json_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(pconline_json_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    phone_data = json.load(f)
                    all_phones.append(phone_data)
            except Exception as e:
                print(f"读取文件失败: {filepath} - {e}")
    
    print(f"总共读取 {len(all_phones)} 个手机数据")
    
    all_phones.sort(key=lambda x: x.get('上市时间', ''), reverse=True)
    
    today = date.today().strftime("%Y%m%d")
    output_file = os.path.join(working_dir, f"pconline_phones_{today}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_phones, f, ensure_ascii=False, indent=2)
    
    print(f"合并数据已保存到: {output_file}")
    
    csv_file = os.path.join(working_dir, f"pconline_phones_{today}.csv")
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
        
        print(f"CSV数据已保存到: {csv_file}")
    
    return all_phones


def step3_generate_summary():
    print("\n" + "="*70)
    print("步骤3：生成统计摘要")
    print("="*70)
    
    total_phones = len(progress.get('crawled_phones', []))
    total_pages = len(progress.get('crawled_pages', []))
    
    print(f"爬取页数: {total_pages}")
    print(f"爬取手机数: {total_phones}")
    
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
    
    print("\n品牌分布:")
    for brand, count in sorted(brand_count.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {brand}: {count} 个")


def main():
    print("太平洋电脑网手机参数爬虫")
    print("="*70)
    
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
