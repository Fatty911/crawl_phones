#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import glob
import json
import os
import re
from datetime import date

DIR = os.path.dirname(os.path.abspath(__file__))

FIXED = ['数据来源', '品牌', '型号', '手机ID', '上市时间', '价格']

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
    '屏幕尺寸': '屏幕',
    '主屏尺寸': '屏幕',
    '分辨率': '屏幕分辨率',
    '主屏分辨率': '屏幕分辨率',
    '后置摄像头': '后置摄像头像素',
    '后置摄像头像素': '后置摄像头像素',
    '前置摄像头': '前置摄像头像素',
    '前置摄像头像素': '前置摄像头像素',
    '电池容量': '电池',
    '电池容量(mAh)': '电池',
    'RAM容量': '内存',
    '运行内存': '内存',
    'ROM容量': '存储',
    '机身存储': '存储',
}


def parse_numbers(value):
    if not value or value == '-':
        return []
    return [float(n) for n in re.findall(r'\d+(?:\.\d+)?', str(value))]


def has_positive_value(value):
    if value is None:
        return False
    text = str(value).strip()
    if not text or text == '-':
        return False
    negative_values = {'无', '不支持', '否', '没有', '未配备', '不提供', '0', '0.0'}
    return text not in negative_values


def norm(header):
    if header in HEADER_MAP:
        return HEADER_MAP[header]
    for key, value in HEADER_MAP.items():
        if key in header or header in key:
            return value
    return header


def find_latest(pattern):
    files = glob.glob(os.path.join(DIR, pattern))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def load(path):
    if not path or not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def norm_rows(rows, source):
    out = []
    for row in rows:
        normalized = {'数据来源': source}
        for key in ['品牌', '型号', '手机ID', '上市时间', '价格']:
            if key in row:
                normalized[key] = row[key]
        
        if 'name' in row and '型号' not in normalized:
            normalized['型号'] = row['name']
        if 'id' in row and '手机ID' not in normalized:
            normalized['手机ID'] = row['id']

        for key, val in row.items():
            if key in FIXED or key in ['id', 'name', 'url', 'crawl_time', 'param_url', 'phone_id']:
                continue
            unified = norm(key)
            if unified in normalized and normalized[unified] not in ('', '-'):
                if val not in ('', '-') and val != normalized[unified]:
                    normalized[unified] = f"{normalized[unified]}|{val}"
            else:
                normalized[unified] = val

        out.append(normalized)
    return out


def diff(zol_rows, pconline_rows, all_fields):
    index = {
        row.get('型号', '').replace(' ', ''): row
        for row in pconline_rows
        if row.get('型号')
    }
    out = []
    for row in zol_rows:
        name = row.get('型号', '')
        if not name:
            continue
        pconline_row = index.get(name.replace(' ', ''))
        if not pconline_row:
            continue
        for field in all_fields:
            zol_val = row.get(field, '-')
            pconline_val = pconline_row.get(field, '-')
            if zol_val != pconline_val and zol_val != '-' and pconline_val != '-':
                out.append({
                    '手机': name,
                    '配置项': field,
                    '中关村在线': zol_val,
                    '太平洋电脑网': pconline_val,
                })
    return out


def collect_fields(rows):
    fields = []
    for row in rows:
        for key in row:
            if key not in FIXED and key not in fields:
                fields.append(key)
    return FIXED + fields


def write_csv(path, rows, fieldnames):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, '-') for key in fieldnames})


def write_json(path, rows):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def main():
    today = date.today().strftime("%Y%m%d")

    zol_file = find_latest("zol_phones_*.json")
    pconline_file = find_latest("pconline_phones_*.json")
    print(f"中关村在线数据: {zol_file}")
    print(f"太平洋电脑网数据: {pconline_file}")

    zol_rows = norm_rows(load(zol_file), '中关村在线')
    pconline_rows = norm_rows(load(pconline_file), '太平洋电脑网')

    if not zol_rows and not pconline_rows:
        print("错误: 没有找到任何数据文件")
        return

    all_rows = zol_rows + pconline_rows
    print(f"中关村在线:{len(zol_rows)} 太平洋电脑网:{len(pconline_rows)} 合计:{len(all_rows)}")

    header = collect_fields(all_rows)

    merged_csv_path = os.path.join(DIR, f"merged_phones_{today}.csv")
    merged_json_path = os.path.join(DIR, f"merged_phones_{today}.json")
    write_csv(merged_csv_path, all_rows, header)
    write_json(merged_json_path, all_rows)

    diffs = []
    if zol_rows and pconline_rows:
        diffs = diff(zol_rows, pconline_rows, header)
        if diffs:
            diff_path = os.path.join(DIR, f"diff_phones_{today}.csv")
            with open(diff_path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['手机', '配置项', '中关村在线', '太平洋电脑网'])
                writer.writeheader()
                writer.writerows(diffs)
            print(f"差异: {len(diffs)} 处")
        else:
            print("无差异")
    else:
        print("跳过差异比较: 只有一个数据源")

    print("完成")
    print(f"  全部合并: {merged_csv_path}")
    print(f"  全部合并: {merged_json_path}")


if __name__ == "__main__":
    main()
