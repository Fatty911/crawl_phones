#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import re
import argparse
from datetime import datetime
from typing import List, Dict, Optional
import requests

parser = argparse.ArgumentParser(description='AI搜索手机BL锁和Root信息')
parser.add_argument('--input', type=str, required=True, help='输入的手机数据JSON文件')
parser.add_argument('--output', type=str, help='输出的JSON文件')
parser.add_argument('--max-phones', type=int, default=0, help='最多搜索手机数，0表示不限制')
parser.add_argument('--delay', type=float, default=2.0, help='请求间隔秒数')
args = parser.parse_args()

working_dir = os.path.dirname(os.path.abspath(__file__))
ai_search_dir = os.path.join(working_dir, 'ai_search')
os.makedirs(ai_search_dir, exist_ok=True)

progress_file = os.path.join(ai_search_dir, 'progress.json')
if os.path.exists(progress_file):
    with open(progress_file, 'r', encoding='utf-8') as f:
        progress = json.load(f)
else:
    progress = {
        'searched_phones': [],
        'failed_phones': [],
        'total_searched': 0,
        'total_failed': 0
    }


def save_progress():
    with open(progress_file, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def build_search_query(phone: Dict) -> str:
    brand = phone.get('品牌', '')
    model = phone.get('型号', '')
    if not model:
        model = phone.get('name', '')
    
    return f"{brand} {model} 解锁BL root 方法"


def parse_ai_response(response_text: str) -> Dict:
    result = {
        '是否可解BL锁': '未知',
        '是否可root': '未知',
        '解锁方式': '未知',
        'root方案': '未知',
        '风险等级': '未知',
        '信息来源': '未知',
        '详细说明': response_text[:500] if response_text else ''
    }
    
    text = response_text.lower()
    
    if any(word in text for word in ['可以解锁', '支持解锁', '官方解锁', '可解bl', '能解锁']):
        result['是否可解BL锁'] = '是'
    elif any(word in text for word in ['无法解锁', '不支持解锁', '锁定', '不能解锁']):
        result['是否可解BL锁'] = '否'
    elif any(word in text for word in ['免解锁', '无需解锁', '直接root']):
        result['是否可解BL锁'] = '免解锁'
    
    if any(word in text for word in ['可以root', '支持root', '已root', '能root']):
        result['是否可root'] = '是'
    elif any(word in text for word in ['无法root', '不支持root', '不能root']):
        result['是否可root'] = '否'
    
    if 'magisk' in text:
        result['root方案'] = 'Magisk'
    elif 'kernelsu' in text:
        result['root方案'] = 'KernelSU'
    elif 'supersu' in text:
        result['root方案'] = 'SuperSU'
    
    if '官方' in text and '申请' in text:
        result['解锁方式'] = '官方申请'
    elif '工程线' in text:
        result['解锁方式'] = '工程线'
    elif '漏洞' in text or 'exploit' in text:
        result['解锁方式'] = '漏洞利用'
    
    if '低风险' in text or '安全' in text:
        result['风险等级'] = '低'
    elif '高风险' in text or '变砖' in text or '危险' in text:
        result['风险等级'] = '高'
    elif '中等' in text:
        result['风险等级'] = '中'
    
    sources = []
    if 'xda' in text:
        sources.append('XDA')
    if '酷安' in text:
        sources.append('酷安')
    if '官方' in text:
        sources.append('官方文档')
    if 'github' in text:
        sources.append('GitHub')
    if sources:
        result['信息来源'] = ', '.join(sources)
    
    return result


def search_with_ai(phone: Dict, api_key: str = None) -> Optional[Dict]:
    query = build_search_query(phone)
    print(f"搜索: {query}")
    
    try:
        result = parse_ai_response(query)
        
        result['搜索时间'] = datetime.now().isoformat()
        result['搜索查询'] = query
        
        return result
        
    except Exception as e:
        print(f"搜索失败: {e}")
        return None


def search_phones(phones: List[Dict], api_key: str = None) -> List[Dict]:
    searched_count = 0
    failed_count = 0
    
    for phone in phones:
        if args.max_phones > 0 and searched_count >= args.max_phones:
            print(f"达到搜索数量限制 ({args.max_phones})")
            break
        
        phone_id = phone.get('id') or phone.get('phone_id') or phone.get('手机ID')
        if not phone_id:
            phone_id = phone.get('型号', '').replace(' ', '_')
        
        if phone_id in progress.get('searched_phones', []):
            print(f"跳过已搜索: {phone.get('型号', phone.get('name', ''))}")
            continue
        
        result = search_with_ai(phone, api_key)
        
        if result:
            phone.update(result)
            searched_count += 1
            progress['searched_phones'].append(phone_id)
            progress['total_searched'] = searched_count
            print(f"✓ 搜索成功: {phone.get('型号', phone.get('name', ''))} - BL:{result['是否可解BL锁']} Root:{result['是否可root']}")
        else:
            failed_count += 1
            progress['failed_phones'].append(phone_id)
            progress['total_failed'] = failed_count
            print(f"✗ 搜索失败: {phone.get('型号', phone.get('name', ''))}")
        
        save_progress()
        time.sleep(args.delay)
    
    print(f"\n搜索完成: 成功 {searched_count}, 失败 {failed_count}")
    return phones


def main():
    print("AI搜索手机BL锁和Root信息")
    print("="*70)
    
    input_file = args.input
    if not os.path.exists(input_file):
        print(f"错误: 输入文件不存在: {input_file}")
        sys.exit(1)
    
    with open(input_file, 'r', encoding='utf-8') as f:
        phones = json.load(f)
    
    print(f"读取 {len(phones)} 个手机数据")
    
    api_key = os.environ.get('AI_API_KEY') or os.environ.get('OPENAI_API_KEY')
    
    phones = search_phones(phones, api_key)
    
    output_file = args.output
    if not output_file:
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_file = os.path.join(working_dir, f"{base_name}_with_root_info.json")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(phones, f, ensure_ascii=False, indent=2)
    
    print(f"\n结果已保存到: {output_file}")
    
    searched = sum(1 for p in phones if p.get('是否可root') != '未知')
    bl_unlock = sum(1 for p in phones if p.get('是否可解BL锁') == '是')
    rootable = sum(1 for p in phones if p.get('是否可root') == '是')
    
    print(f"\n统计:")
    print(f"  已搜索: {searched}/{len(phones)}")
    print(f"  可解BL锁: {bl_unlock}")
    print(f"  可Root: {rootable}")


if __name__ == '__main__':
    main()
