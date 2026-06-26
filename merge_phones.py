#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import glob
import json
import os
import re
from datetime import date

DIR = os.path.dirname(os.path.abspath(__file__))

FIXED = [
    '数据来源',
    '验证状态',
    '交叉验证差异',
    '品牌',
    '型号',
    '手机ID',
    '上市时间',
    '价格',
    '机身宽度',
    '机身尺寸',
    '摄像头参数',
    '超广角缩放倍数',
]

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


def clean_value(value):
    if value is None:
        return value
    text = str(value)
    text = text.replace('纠错', '')
    text = re.sub(r'\s+', ' ', text).strip()
    return text if text else '-'


def is_missing(value):
    if value is None:
        return True
    return str(value).strip() in ('', '-')


def semantic_value_equal(a, b):
    """判断两个属性值语义是否相同（文本不完全一致但意思一样也算一致）。

    处理：空白符差异、常见修饰词（支持/内置/配备/搭载/采用/具备）、单位间距、HTML链接后缀。
    例：'支持5G' == '5G', '5000 mAh' == '5000mAh', '6.7英寸' == '6.7 英寸'
    """
    if a == b:
        return True
    if a is None or b is None:
        return False
    a_clean = re.sub(r'\s+', '', str(a))
    b_clean = re.sub(r'\s+', '', str(b))
    if a_clean == b_clean:
        return True
    # 去掉 ZOL 常见的 HTML 括号链接后缀 (如 "5G>" → "5G")
    a_clean = re.sub(r'>.*$', '', a_clean)
    b_clean = re.sub(r'>.*$', '', b_clean)
    if a_clean == b_clean:
        return True
    # 去掉常见修饰前缀
    modifiers = ['支持', '内置', '配备', '搭载', '采用', '具备', '拥有']
    for m in modifiers:
        a_stripped = re.sub(r'^' + m, '', a_clean)
        b_stripped = re.sub(r'^' + m, '', b_clean)
        if a_stripped == b_clean or a_clean == b_stripped or a_stripped == b_stripped:
            return True
    return False


def model_key(row):
    raw_name = row.get('型号') or row.get('name') or ''
    if is_missing(raw_name):
        return ''
    name = clean_value(raw_name)
    if is_missing(name):
        return ''
    name = re.sub(r'\s+', '', name).lower()
    # 去除存储容量后缀（括号形式）
    name = re.sub(r'[（(]\d+gb(?:/\d+gb)?[）)]', '', name)
    # 去除末尾裸存储容量后缀
    name = re.sub(r'\d+gb$', '', name)
    # 去除常见后缀
    for suffix in ['5g', '4g', 'wifi']:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name


def fuzzy_model_key(row):
    """更激进的模糊匹配键"""
    key = model_key(row)
    if not key:
        return ''
    key = re.sub(r'[（(].*?[）)]', '', key)
    key = key.replace('.', '').replace('-', '')
    return key


def norm(header):
    if header in HEADER_MAP:
        return HEADER_MAP[header]
    for key, value in HEADER_MAP.items():
        if key in header or header in key:
            return value
    return header


def first_number_text(value):
    match = re.search(r'\d+(?:\.\d+)?', str(value or ''))
    return match.group(0) if match else ''


def derive_body_size(row):
    if has_positive_value(row.get('机身尺寸')):
        return clean_value(row.get('机身尺寸'))

    length = first_number_text(row.get('机身长度'))
    width = first_number_text(row.get('机身宽度'))
    thickness = first_number_text(row.get('机身厚度'))
    if length and width and thickness:
        return f"{length} x {width} x {thickness} mm"
    return ''


def derive_body_width(row):
    if has_positive_value(row.get('机身宽度')):
        value = clean_value(row.get('机身宽度'))
        number = first_number_text(value)
        return f"{number} mm" if number else value

    size = row.get('机身尺寸')
    numbers = parse_numbers(size)
    if len(numbers) >= 2:
        return f"{numbers[1]:g} mm"
    return ''


def derive_camera_summary(row):
    parts = []
    labels = [
        ('后置', '后置摄像头像素'),
        ('前置', '前置摄像头像素'),
        ('镜头', '摄像头名称'),
        ('数量', '摄像头总数'),
        ('变焦', '变焦倍数'),
        ('传感器', '传感器尺寸'),
        ('焦距', '焦距'),
        ('特色', '摄像头特色'),
        ('视频', '后置视频拍摄'),
        ('前置视频', '前置视频拍摄'),
        ('其他', '其他摄像头参数'),
    ]
    for label, key in labels:
        value = row.get(key)
        if has_positive_value(value):
            text = clean_value(value)
            if f"{label}:" not in text and f"{label}：" not in text:
                text = f"{label}: {text}"
            parts.append(text)
    return '；'.join(parts)


def derive_ultrawide_zoom(row):
    text = ' '.join(
        clean_value(row.get(key, ''))
        for key in [
            '摄像头名称',
            '变焦倍数',
            '焦距',
            '其他摄像头参数',
            '摄像头参数',
        ]
        if has_positive_value(row.get(key))
    )
    if not text:
        return ''

    patterns = [
        r'超广角.{0,24}?((?:0\.\d+|1(?:\.0+)?)\s*(?:x|X|倍))',
        r'((?:0\.\d+|1(?:\.0+)?)\s*(?:x|X|倍)).{0,24}?超广角',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return re.sub(r'\s+', '', match.group(1))
    return ''


def add_derived_fields(row):
    body_size = derive_body_size(row)
    if body_size:
        row['机身尺寸'] = body_size

    body_width = derive_body_width(row)
    if body_width:
        row['机身宽度'] = body_width

    camera_summary = derive_camera_summary(row)
    if camera_summary:
        row['摄像头参数'] = camera_summary

    ultrawide_zoom = derive_ultrawide_zoom(row)
    if ultrawide_zoom:
        row['超广角缩放倍数'] = ultrawide_zoom


def find_latest(pattern):
    files = glob.glob(os.path.join(DIR, pattern))
    if not files:
        files = glob.glob(os.path.join(DIR, '**', pattern), recursive=True)
    if not files:
        return None
    data_files = [f for f in files if 'progress' not in f and 'manifest' not in f]
    if not data_files:
        data_files = files
    return max(data_files, key=os.path.getmtime)


def load_all(pattern):
    """加载所有匹配文件并合并为去重列表（按手机ID去重）"""
    files = glob.glob(os.path.join(DIR, pattern))
    if not files:
        files = glob.glob(os.path.join(DIR, '**', pattern), recursive=True)
    data_files = [f for f in files if 'progress' not in f and 'manifest' not in f]
    if not data_files:
        data_files = files

    all_rows = []
    seen_ids = set()
    for path in sorted(data_files, key=os.path.getmtime):
        rows = load(path)
        for row in rows:
            phone_id = row.get('手机ID') or row.get('id') or row.get('型号', '') or row.get('name', '')
            key = str(phone_id).strip().lower().replace(' ', '')
            if key and key in seen_ids:
                continue
            if key:
                seen_ids.add(key)
            all_rows.append(row)
    return all_rows


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

        # 品牌回填：如果爬虫未提供品牌，从型号名推导
        if not normalized.get('品牌') or normalized['品牌'] == '-':
            model_name = normalized.get('型号', row.get('name', ''))
            derived = derive_brand_from_name(model_name)
            if derived:
                normalized['品牌'] = derived

        for key, val in row.items():
            if key in FIXED or key in ['id', 'name', 'url', 'crawl_time', 'param_url', 'phone_id']:
                continue
            unified = norm(key)
            if unified in normalized and normalized[unified] not in ('', '-'):
                value = clean_value(val)
                if value not in ('', '-') and value != normalized[unified]:
                    normalized[unified] = f"{normalized[unified]}|{value}"
            else:
                normalized[unified] = clean_value(val)

        add_derived_fields(normalized)

        out.append(normalized)
    return out


def merge_verified_rows(zol_rows, pconline_rows, all_fields):
    # 第一级索引: 精确匹配
    pconline_exact = {}
    # 第二级索引: 模糊匹配
    pconline_fuzzy = {}
    for row in pconline_rows:
        exact = model_key(row)
        fuzzy = fuzzy_model_key(row)
        if exact:
            pconline_exact[exact] = row
        if fuzzy and fuzzy != exact:
            pconline_fuzzy[fuzzy] = row
    used_pconline = set()
    merged = []

    def combine_rows(zol_row, pconline_row):
        combined = {}
        differences = []
        for field in all_fields:
            if field in ('数据来源', '验证状态', '交叉验证差异'):
                continue
            zol_val = clean_value(zol_row.get(field, '-'))
            pc_val = clean_value(pconline_row.get(field, '-'))
            if is_missing(zol_val) and is_missing(pc_val):
                continue
            if is_missing(zol_val):
                combined[field] = pc_val
            elif is_missing(pc_val):
                combined[field] = zol_val
            elif semantic_value_equal(zol_val, pc_val):
                combined[field] = zol_val  # 优先保留简洁版（通常ZOL更规范）
            else:
                combined[field] = f"中关村在线: {zol_val} | 太平洋电脑网: {pc_val}"
                differences.append(f"{field}: 中关村在线={zol_val}; 太平洋电脑网={pc_val}")

        combined['数据来源'] = '中关村在线+太平洋电脑网'
        combined['验证状态'] = '双源差异' if differences else '双源一致'
        combined['交叉验证差异'] = '；'.join(differences) if differences else '-'
        return combined

    for zol_row in zol_rows:
        key = model_key(zol_row)
        pconline_row = pconline_exact.get(key)
        if not pconline_row:
            fuzzy = fuzzy_model_key(zol_row)
            pconline_row = pconline_fuzzy.get(fuzzy)
        if pconline_row:
            used_pconline.add(model_key(pconline_row))
            merged.append(combine_rows(zol_row, pconline_row))
            continue
        row = dict(zol_row)
        row['数据来源'] = '中关村在线'
        row['验证状态'] = '单源'
        row.setdefault('交叉验证差异', '-')
        merged.append(row)

    for pconline_row in pconline_rows:
        key = model_key(pconline_row)
        if key in used_pconline:
            continue
        row = dict(pconline_row)
        row['数据来源'] = '太平洋电脑网'
        row['验证状态'] = '单源'
        row.setdefault('交叉验证差异', '-')
        merged.append(row)

    return merged


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
    today = os.environ.get("MERGE_DATE") or date.today().strftime("%Y%m%d")

    zol_files = sorted(glob.glob(os.path.join(DIR, "zol_phones_*.json")))
    pconline_files = sorted(glob.glob(os.path.join(DIR, "pconline_phones_*.json")))
    print(f"中关村在线数据文件 ({len(zol_files)}): {[os.path.basename(f) for f in zol_files]}")
    print(f"太平洋电脑网数据文件 ({len(pconline_files)}): {[os.path.basename(f) for f in pconline_files]}")

    zol_rows = norm_rows(load_all("zol_phones_*.json"), '中关村在线')
    pconline_rows = norm_rows(load_all("pconline_phones_*.json"), '太平洋电脑网')

    if not zol_rows and not pconline_rows:
        print("错误: 没有找到任何数据文件")
        return

    source_rows = zol_rows + pconline_rows
    print(f"中关村在线:{len(zol_rows)} 太平洋电脑网:{len(pconline_rows)} 合计:{len(source_rows)}")

    source_header = collect_fields(source_rows)
    all_rows = merge_verified_rows(zol_rows, pconline_rows, source_header)
    header = collect_fields(all_rows)
    dual_source_count = sum(1 for row in all_rows if row.get('验证状态', '').startswith('双源'))
    print(f"交叉验证后机型:{len(all_rows)} 双源记录:{dual_source_count} 单源记录:{len(all_rows) - dual_source_count}")

    merged_csv_path = os.path.join(DIR, f"merged_phones_{today}.csv")
    merged_json_path = os.path.join(DIR, f"merged_phones_{today}.json")
    write_csv(merged_csv_path, all_rows, header)
    write_json(merged_json_path, all_rows)

    diffs = []
    if zol_rows and pconline_rows:
        diffs = diff(zol_rows, pconline_rows, source_header)
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
