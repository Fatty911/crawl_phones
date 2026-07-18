#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import glob
import json
import os
import re
import unicodedata
from datetime import date

DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(DIR)

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

VALIDATION_FIELDS = ('处理器', '内存', '存储', '屏幕', '电池', '摄像头参数', '上市时间')
VALIDATION_MISSING_VALUES = {'', '-', '--', '/', 'n/a', 'null', '暂无', '无', '未知'}
SOURCE_VALIDATION_ROWS_FIELD = '_source_validation_rows'
FAMILY_CONFIG_MISMATCH_STATUS = '型号多源（配置未匹配）'
FAMILY_CONFIG_MISMATCH_DIFFERENCE = '同一基础型号在其他来源存在，但内存/存储配置未一一匹配'
PUBLISH_SPEC_FIELDS = (
    '处理器', '内存', '存储', '屏幕', '电池', '摄像头参数',
    '机身尺寸', '机身厚度', '机身重量', '网络类型', '机身接口', '有线充电',
)
CNMO_MIN_PUBLISH_SPEC_COUNT = 2

HEADER_MAP = {
    '国内发布时间': '上市时间',
    '发布时间': '上市时间',
    '发布日期': '上市时间',
    '上市日期': '上市时间',
    '电商报价': '价格',
    '售价': '价格',
    '报价': '价格',
    'brand': '品牌',
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
    '后置相机': '摄像头参数',
    '后置摄像头像素': '摄像头参数',
    '前置摄像头': '摄像头参数',
    '前置相机': '摄像头参数',
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
    'RAM存储类型': '内存',
    'ROM容量': '存储',
    '机身存储': '存储',
    '机身容量': '存储',
    '存储': '存储',
    'ROM存储类型': '存储',
    '存储类型': '存储',
    '存储卡': '存储',
    '扩展卡': '存储',
    '扩展容量': '存储',
    '机身尺寸': '机身尺寸',
    '尺寸': '机身尺寸',
    '长度': '机身长度',
    '宽度': '机身宽度',
    '厚度': '机身厚度',
    '重量': '机身重量',
    '机身重量': '机身重量',
}


_PRICE_PATTERN = re.compile(r"\d+(?:\.\d+)?")
_RELEASE_DATE_PATTERN = re.compile(
    r"(?<!\d)((?:19|20)\d{2})(?:\s*[年\-/.]\s*(\d{1,2}))?(?:\s*[月\-/.]\s*(\d{1,2}))?"
)


def normalize_cnmo_price(value):
    if value is None:
        return ''
    text = str(value).strip().replace('￥', '').replace('¥', '').replace(',', '')
    return text if _PRICE_PATTERN.fullmatch(text) else ''


def is_future_release(row, today=None):
    today = today or date.today()
    for key in ['上市时间', '国内发布时间', '发布时间', '发布日期', '上市日期']:
        match = _RELEASE_DATE_PATTERN.search(str(row.get(key, '') or ''))
        if not match:
            continue
        year = int(match.group(1))
        month = int(match.group(2)) if match.group(2) else None
        day = int(match.group(3)) if match.group(3) else None
        if month is None:
            return year > today.year
        if day is None:
            return (year, month) > (today.year, today.month)
        try:
            return date(year, month, day) > today
        except ValueError:
            return False
    return False


def is_meaningful_publish_spec(value):
    if is_validation_missing(value):
        return False
    text = unicodedata.normalize('NFKC', str(value)).strip().casefold()
    residue = re.sub(r'[\s\-—_/|•>；;：:,，]+', '', text)
    residue = re.sub(r'(?:核心数|运行内存|处理器|屏幕|电池|内存|存储)', '', residue)
    return residue not in {'', '无', '不支持', '否', '暂无', '未知', 'null', 'n/a'}


def publish_spec_count(row):
    return sum(is_meaningful_publish_spec(row.get(field)) for field in PUBLISH_SPEC_FIELDS)


def is_low_quality_cnmo_single_source(row):
    source = str(row.get('数据来源') or row.get('source') or '').strip()
    return source == 'CNMO' and publish_spec_count(row) < CNMO_MIN_PUBLISH_SPEC_COUNT


def guard_publish_rows(rows, source=None, today=None):
    guarded = []
    for row in rows:
        if is_future_release(row, today):
            continue
        if source == 'CNMO' and publish_spec_count(row) < CNMO_MIN_PUBLISH_SPEC_COUNT:
            continue
        clean = dict(row)
        if source == 'CNMO':
            clean['价格'] = normalize_cnmo_price(clean.get('价格'))
        guarded.append(clean)
    return guarded

# 手机品牌别名映射（归一化到标准品牌名）
BRAND_ALIASES = {
    # vivo 系列
    '步步高': 'vivo',
    'vivo': 'vivo',
    # 红米/小米系列
    '红米': '红米',
    'redmi': '红米',
    '小米': '小米',
    'xiaomi': '小米',
    'poco': '小米',
    # OPPO 系
    'oppo': 'OPPO',
    'OPPO': 'OPPO',
    '一加': '一加',
    'oneplus': '一加',
    '真我': '真我',
    'realme': '真我',
    'iqoo': 'iQOO',
    'iQOO': 'iQOO',
    # 华为/荣耀
    '华为': '华为',
    'huawei': '华为',
    '荣耀': '荣耀',
    'honor': '荣耀',
    # 三星
    '三星': '三星',
    'samsung': '三星',
    # 苹果
    '苹果': '苹果',
    'apple': '苹果',
    'iphone': '苹果',
    'ipad': '苹果',
    # 其他
    '魅族': '魅族',
    'meizu': '魅族',
    '中兴': '中兴',
    'zte': '中兴',
    '努比亚': '努比亚',
    'nubia': '努比亚',
    '联想': '联想',
    'lenovo': '联想',
    '摩托罗拉': '摩托罗拉',
    'moto': '摩托罗拉',
    'motorola': '摩托罗拉',
    '索尼': '索尼',
    'sony': '索尼',
    'xperia': '索尼',
    '谷歌': '谷歌',
    'google': '谷歌',
    'pixel': '谷歌',
    '诺基亚': '诺基亚',
    'nokia': '诺基亚',
    'nothing': 'Nothing',
    '传音': '传音',
    'tecno': '传音',
    'itel': '传音',
    'infinix': '传音',
    '乐视': '乐视',
    'letv': '乐视',
    '金立': '金立',
    'gionee': '金立',
    '蔚来': '蔚来',
    'nio': '蔚来',
    '鼎桥': '鼎桥',
    'td tech': '鼎桥',
    '魅蓝': '魅蓝',
    '酷派': '酷派',
    'coolpad': '酷派',
    '海信': '海信',
    'hisense': '海信',
    '多亲': '多亲',
    'qin': '多亲',
    'wiko': 'WIKO',
    '麦芒': '麦芒',
    '华硕': '华硕',
    'asus': '华硕',
    'rog': '华硕',
    '黑鲨': '黑鲨',
    'black shark': '黑鲨',
    'nzone': 'NZONE',
    'lg': 'LG',
}

CNMO_SINGLE_SOURCE_ALLOWED_BRANDS = {
    '苹果', '三星', '华为', '荣耀', 'OPPO', 'vivo', '小米', '红米', 'iQOO',
    '一加', '真我', '魅族', '中兴', '努比亚', '联想', '摩托罗拉',
    '乐视', '金立', '蔚来', '鼎桥', '魅蓝', '酷派', '海信', 'WIKO',
    '麦芒', '华硕', '黑鲨', 'NZONE', 'Hi nova', '天翼铂顿',
    '多亲',
}

# 从型号名推导品牌的模式（按优先级排序，越具体越靠前）
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
    ('乐视', ['乐视', 'letv']),
    ('金立', ['金立', 'gionee']),
    ('蔚来', ['蔚来', 'nio phone']),
    ('鼎桥', ['鼎桥', 'td tech']),
    ('魅蓝', ['魅蓝']),
    ('酷派', ['酷派', 'coolpad', 'cool ']),
    ('海信', ['海信', 'hisense']),
    ('多亲', ['多亲', 'qin3', 'qin 3']),
    ('WIKO', ['wiko', 'hi 畅享', 'hi畅享']),
    ('麦芒', ['麦芒']),
    ('Hi nova', ['hi nova', 'hinova']),
    ('天翼铂顿', ['天翼铂顿']),
    ('华硕', ['华硕', 'asus', 'rog游戏手机', 'rog game']),
    ('黑鲨', ['黑鲨', 'black shark']),
    ('NZONE', ['nzone']),
    ('LG', ['lg ']),
]

def normalize_brand(brand: str) -> str:
    """将品牌名归一化为标准名称"""
    if not brand:
        return ''
    # 先尝试直接映射
    brand_stripped = brand.strip()
    if brand_stripped in BRAND_ALIASES:
        return BRAND_ALIASES[brand_stripped]
    # 再尝试小写匹配
    brand_lower = brand_stripped.lower()
    if brand_lower in BRAND_ALIASES:
        return BRAND_ALIASES[brand_lower]
    # 最后用模式匹配兜底
    return derive_brand_from_name(brand_stripped)

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

def is_cnmo_single_source_in_publish_scope(row):
    brand = normalize_brand(row.get('品牌') or derive_brand_from_name(row.get('型号', '')))
    return brand in CNMO_SINGLE_SOURCE_ALLOWED_BRANDS


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


def clean_spec_value(field, value):
    text = clean_value(value)
    if field not in ('内存', '存储') or text == '-':
        return text
    if field == '内存':
        text = re.sub(r'游戏运行(?:流畅|良好|一般)', '', text)
    else:
        text = re.sub(r'(?:约)?\d+(?:\.\d+)?\s*万?\s*张照片', '', text)
        text = re.sub(r'(?:约)?\d+(?:\.\d+)?\s*万?\s*首歌曲', '', text)
        text = text.replace('无扩展卡功能', '不支持容量扩展')
    text = re.sub(r'[（(]\s*[、,，/|•>；;]*\s*[）)]', '', text)
    text = re.sub(r'\s*[、,，/|•>；;]+\s*', '|', text).strip(' |')
    return text if text else '-'

def is_missing(value):
    if value is None:
        return True
    return str(value).strip() in ('', '-')


def extract_core_keywords(text: str) -> set:
    """提取核心关键词：型号、频率、容量、尺寸、版本号等"""
    if not text:
        return set()
    text = str(text)
    keywords = set()
    
    # 提取型号/版本号（字母数字组合，如 SM8650, 天玑9400, 骁龙8Gen3, IMX882 等）
    model_patterns = [
        r'[A-Z]{2,}\d+[A-Z]*',  # SM8650, IMX882, LPDDR5X 等
        r'[A-Za-z]+[- ]?\d+[A-Za-z]*',  # 骁龙8Gen3, 天玑9400+, IMX882 等
        r'\d+\.?\d*[GM]Hz',  # 3.0GHz, 2.8GHz 等
        r'\d+[GM]B',  # 256GB, 12GB, 5000mAh 等
        r'\d+\.?\d*\s*(?:英寸|寸|mm|ppi|nits|Hz)',  # 6.7英寸, 120Hz, 4500nits 等
        r'\d+\.?\d*[x×]\d+',  # 2800x1260, 2750×1260 等分辨率
        r'[A-Z]{2,}\d+',  # UFS4.1, LPDDR5X 等
    ]
    for pat in model_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            keywords.add(m.group().upper().replace(' ', '').replace('×', 'X'))
    
    # 提取中文处理器型号（关键新增）
    cn_processor_patterns = [
        r'(骁龙|天玑|麒麟|Exynos|Tensor|A系列)\s*\d+\w*',
        r'(联发科|高通|三星|苹果)\s*[\w\s\+\-]*\d+\w*',
        r'(天玑|骁龙|麒麟)\s*\d+\s*[\w\+\-]*',
    ]
    for pat in cn_processor_patterns:
        for m in re.finditer(pat, text):
            keywords.add(m.group().replace(' ', ''))
    
    # 提取关键中文词汇（处理器系列、屏幕材质、系统版本等）
    chinese_keywords = [
        '骁龙', '天玑', '麒麟', 'Exynos', 'Tensor', 'A系列',
        'AMOLED', 'OLED', 'LCD', 'LTPO', 'E5', 'E6', 'E7',
        'OriginOS', 'HyperOS', 'MIUI', 'ColorOS', 'MagicOS', 'OneUI',
        'UFS', 'LPDDR', 'DDR',
        'IMX', 'HP', 'LYT', 'JN', 'OV', 'S5K',
        '潜望', '超广角', '长焦', '微距', '主摄', '前置',
        '快充', '无线充', '反向充',
        'IP68', 'IP69', '防水', '防尘',
        '超声波', '光学', '短焦', '指纹',
        '5G', 'WiFi', '蓝牙', 'NFC', '红外',
        '双卡', '单卡', 'eSIM',
    ]
    for kw in chinese_keywords:
        if kw in text:
            keywords.add(kw)
    
    return keywords


def keyword_overlap_score(a: str, b: str) -> float:
    """计算两个文本的核心关键词重叠度（0-1）"""
    ka = extract_core_keywords(a)
    kb = extract_core_keywords(b)
    if not ka and not kb:
        return 1.0
    if not ka or not kb:
        return 0.0
    intersection = ka & kb
    union = ka | kb
    return len(intersection) / len(union)


def length_ratio(a: str, b: str) -> float:
    """计算长度比（较短/较长），用于判断是否为详细程度差异"""
    la = len(str(a).strip())
    lb = len(str(b).strip())
    if la == 0 and lb == 0:
        return 1.0
    if la == 0 or lb == 0:
        return 0.0
    return min(la, lb) / max(la, lb)


def semantic_value_equal(a, b):
    """判断两个属性值语义是否相同（文本不完全一致但意思一样也算一致）。
    
    核心逻辑：
    1. 完全相等 -> True
    2. 去除空白/修饰词/HTML后缀后相等 -> True
    3. 核心关键词重叠度 ≥ 0.7 且 长度比 ≥ 0.3 -> True（视为描述详略差异）
    4. 否则 -> False（视为真实差异）
    """
    if a == b:
        return True
    if a is None or b is None:
        return False
    
    a_str = str(a)
    b_str = str(b)
    
    # 基础清理
    a_clean = re.sub(r'\s+', '', a_str)
    b_clean = re.sub(r'\s+', '', b_str)
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
    
    # 关键新增：基于核心关键词重叠度 + 长度比 判断是否为"描述详略差异"
    # 核心关键词重叠度高（≥0.7）且长度比不太悬殊（≥0.3）-> 视为语义一致
    overlap = keyword_overlap_score(a_str, b_str)
    ratio = length_ratio(a_str, b_str)
    
    if overlap >= 0.7 and ratio >= 0.3:
        return True
    
    # 特殊处理：存储字段（ZOL 单一配置 vs PConline 多配置列表）
    # 如 "256GB" vs "256GB,512GB" -> 取交集非空即一致
    storage_a = set(re.findall(r'\d+GB', a_str, re.IGNORECASE))
    storage_b = set(re.findall(r'\d+GB', b_str, re.IGNORECASE))
    if storage_a and storage_b and storage_a & storage_b:
        return True
    
    # 特殊处理：内存字段
    mem_a = set(re.findall(r'\d+GB', a_str, re.IGNORECASE))
    mem_b = set(re.findall(r'\d+GB', b_str, re.IGNORECASE))
    if mem_a and mem_b and mem_a & mem_b:
        return True
    
    # 特殊处理：操作系统（提取系统名+版本号比较）
    os_patterns = r'(OriginOS|Android|ColorOS|MagicOS|MIUI|HyperOS|OneUI|iOS|HarmonyOS|Flyme)\s*(\d+(?:\.\d+)?)?'
    os_a = re.search(os_patterns, a_str)
    os_b = re.search(os_patterns, b_str)
    if os_a and os_b:
        base_a = os_a.group(1)
        base_b = os_b.group(1)
        ver_a = os_a.group(2) or ''
        ver_b = os_b.group(2) or ''
        if base_a == base_b and (not ver_a or not ver_b or ver_a == ver_b):
            return True
        # 特殊：一个只有系统名，另一个有系统名+Android版本，如 "MagicOS 10" vs "Android 16,MagicOS 10"
        if base_a == base_b or base_a in b_str or base_b in a_str:
            return True
    
    # 特殊处理：处理器 - 提取核心型号比较
    # 如 "联发科 天玑 8550 SUPER" vs "联发科(MTK)•...|1超大核+3大核+4中核（最高频率3.4GHz）"
    proc_patterns = [
        r'(骁龙\s*8\s*Elite|骁龙\s*8\s*Gen\d+|天玑\s*\d+\w*|麒麟\s*\d+\w*|骁龙|天玑|麒麟|Exynos|Tensor|A系列|Apple\s*A\d+)',
        r'(联发科|高通|三星|苹果)\s*[\w\s\+\-]*\d+\w*',
    ]
    for pat in proc_patterns:
        proc_a = re.findall(pat, a_str, re.IGNORECASE)
        proc_b = re.findall(pat, b_str, re.IGNORECASE)
        if proc_a and proc_b:
            # 简化：取第一个匹配
            first_a = proc_a[0] if isinstance(proc_a[0], str) else ''.join(proc_a[0]).replace(' ', '')
            first_b = proc_b[0] if isinstance(proc_b[0], str) else ''.join(proc_b[0]).replace(' ', '')
            # 检查核心型号是否包含（处理 Elite/Pro/Ultra 等后缀变体）
            core_a = re.sub(r'\s*(Elite|Pro|Ultra|Plus|Super|MAX)\s*$', '', first_a, flags=re.IGNORECASE)
            core_b = re.sub(r'\s*(Elite|Pro|Ultra|Plus|Super|MAX)\s*$', '', first_b, flags=re.IGNORECASE)
            if core_a in core_b or core_b in core_a or core_a == core_b:
                return True
    
    # 特殊处理：价格（数值相等即一致，忽略小数点格式）
    price_a = re.search(r'[\d,]+\.?\d*', a_str.replace('￥', '').replace('¥', '').replace(',', ''))
    price_b = re.search(r'[\d,]+\.?\d*', b_str.replace('￥', '').replace('¥', '').replace(',', ''))
    if price_a and price_b:
        try:
            if abs(float(price_a.group()) - float(price_b.group())) < 0.01:
                return True
        except:
            pass
    
    # 特殊处理：上市时间（年月日一致即一致）
    date_a = re.search(r'(\d{4})[年\-,.\s]*(\d{1,2})[月\-,.\s]*(\d{1,2})?', a_str)
    date_b = re.search(r'(\d{4})[年\-,.\s]*(\d{1,2})[月\-,.\s]*(\d{1,2})?', b_str)
    if date_a and date_b:
        if date_a.group(1) == date_b.group(1) and date_a.group(2) == date_b.group(2):
            return True
    
    # 特殊处理：屏幕字段 - 核心参数一致即可
    screen_keywords_a = set(re.findall(r'(AMOLED|OLED|LCD|LTPO|E[567]|120Hz|144Hz|60Hz|LTPO|HDR|P3|杜比|nits|英寸|分辨率|\d+x\d+)', a_str, re.IGNORECASE))
    screen_keywords_b = set(re.findall(r'(AMOLED|OLED|LCD|LTPO|E[567]|120Hz|144Hz|60Hz|LTPO|HDR|P3|杜比|nits|英寸|分辨率|\d+x\d+)', b_str, re.IGNORECASE))
    if screen_keywords_a and screen_keywords_b:
        scr_overlap = len(screen_keywords_a & screen_keywords_b) / len(screen_keywords_a | screen_keywords_b)
        if scr_overlap >= 0.5:
            return True
    
    # 特殊处理：电池/充电字段
    battery_keywords_a = set(re.findall(r'(\d+mAh|快充|无线充|反向充|有线充|PD|QC|SuperVOOC|FlashCharge|WarpCharge)', a_str, re.IGNORECASE))
    battery_keywords_b = set(re.findall(r'(\d+mAh|快充|无线充|反向充|有线充|PD|QC|SuperVOOC|FlashCharge|WarpCharge)', b_str, re.IGNORECASE))
    if battery_keywords_a and battery_keywords_b:
        bat_overlap = len(battery_keywords_a & battery_keywords_b) / len(battery_keywords_a | battery_keywords_b)
        if bat_overlap >= 0.5:
            return True
    
    # 特殊处理：蓝牙版本
    bt_a = re.search(r'蓝牙\s*(\d+\.?\d*)', a_str, re.IGNORECASE)
    bt_b = re.search(r'蓝牙\s*(\d+\.?\d*)', b_str, re.IGNORECASE)
    if bt_a and bt_b and bt_a.group(1) == bt_b.group(1):
        return True
    
    # 特殊处理：蓝牙字段 - ZOL 列出编解码器，PConline 只说"支持蓝牙"，核心都支持蓝牙即一致
    if '蓝牙' in a_str and '蓝牙' in b_str:
        # 如果一方只有"支持蓝牙"而另一方列出编解码器，视为一致
        if ('支持蓝牙' in a_str or '支持蓝牙' in b_str) and not ('SBC' in a_str and 'SBC' not in b_str):
            return True
    
    # 特殊处理：SIM卡类型
    sim_a = re.search(r'(nano|micro|eSIM|双卡|单卡)', a_str, re.IGNORECASE)
    sim_b = re.search(r'(nano|micro|eSIM|双卡|单卡)', b_str, re.IGNORECASE)
    if sim_a and sim_b and sim_a.group(1).lower() == sim_b.group(1).lower():
        return True
    
    # 特殊处理：机身重量/尺寸（数值相等即一致）
    dim_a = re.search(r'(\d+\.?\d*)\s*(g|mm)', a_str)
    dim_b = re.search(r'(\d+\.?\d*)\s*(g|mm)', b_str)
    if dim_a and dim_b and dim_a.group(2) == dim_b.group(2):
        try:
            if abs(float(dim_a.group(1)) - float(dim_b.group(1))) < 1:
                return True
        except:
            pass
    
    # 特殊处理：闪光灯 - ZOL 详细类型，PConline 只说 LED 闪光灯，核心都有闪光灯即一致
    if '闪光灯' in a_str and '闪光灯' in b_str:
        if ('LED闪光灯' in a_str and 'LED' in b_str) or ('LED闪光灯' in b_str and 'LED' in a_str):
            return True
        # 都包含"闪光灯"关键词，视为一致
        return True
    
    # 特殊处理：电池 - 核心容量一致即可，忽略品牌名称
    bat_cap_a = set(re.findall(r'(\d+mAh)', a_str, re.IGNORECASE))
    bat_cap_b = set(re.findall(r'(\d+mAh)', b_str, re.IGNORECASE))
    if bat_cap_a and bat_cap_b and bat_cap_a & bat_cap_b:
        return True
    
    return False


def is_validation_missing(value):
    if value is None:
        return True
    return str(value).strip().casefold() in VALIDATION_MISSING_VALUES


def normalize_validation_value(field, value):
    text = unicodedata.normalize('NFKC', str(value)).strip().casefold()
    text = text.replace('纠错', '')
    if field == '上市时间':
        match = re.search(r'((?:19|20)\d{2})\D*(\d{1,2})?\D*(\d{1,2})?', text)
        if match:
            return tuple(int(part) if part else 0 for part in match.groups())
    return re.sub(r'\s+', '', text)


def validation_value_equal(field, left, right):
    return normalize_validation_value(field, left) == normalize_validation_value(field, right)


def classify_source_agreement(source_rows):
    """按七个关键字段保守判定一至三源的一致性。"""
    names = list(source_rows)
    if len(names) < 2:
        return '单源', '-'
    if len(names) > 3:
        return '多源未校验', '来源数量超过三源判定范围'

    missing = []
    for name, row in source_rows.items():
        for field in VALIDATION_FIELDS:
            if is_validation_missing(row.get(field)):
                missing.append(f'{name}缺失{field}')
    if missing:
        return '多源未校验', '；'.join(missing)

    def rows_equal(left, right):
        return all(
            validation_value_equal(field, left.get(field), right.get(field))
            for field in VALIDATION_FIELDS
        )

    equal_pairs = []
    for left_index, left_name in enumerate(names):
        for right_name in names[left_index + 1:]:
            if rows_equal(source_rows[left_name], source_rows[right_name]):
                equal_pairs.append((left_name, right_name))

    differences = []
    for field in VALIDATION_FIELDS:
        values = [source_rows[name].get(field) for name in names]
        if not all(validation_value_equal(field, values[0], value) for value in values[1:]):
            detail = '; '.join(f'{name}={source_rows[name].get(field)}' for name in names)
            differences.append(f'{field}: {detail}')
    difference_text = '；'.join(differences) if differences else '-'

    if len(names) == 2:
        return ('双源一致', '-') if equal_pairs else ('双源差异', difference_text)
    if len(equal_pairs) == 3:
        return '三源一致', '-'
    if equal_pairs:
        return '双源一致', difference_text
    return '三源差异', difference_text


def model_key(row):
    raw_name = row.get('型号') or row.get('name') or ''
    if is_missing(raw_name):
        return ''
    name = clean_value(raw_name).lower()
    if is_missing(name):
        return ''
    # 先在保留空格的原文本中删除容量尾巴，避免把 Pura 90 12GB+512GB 误读成 Pura 9012GB+512GB。
    name = re.sub(
        r'[（(](?:\d+\s*(?:[gt]b)?\s*[+/]+\s*\d+\s*[gt]b?|\d+\s*[gt]b?)'
        r'(?:\s*/\s*(?:全网通|[45]g版|wifi版))*[)）]',
        '',
        name,
        flags=re.IGNORECASE,
    )
    name = re.sub(
        r'(?<![a-z0-9])(?:\d+\s*(?:[gt]b)?\s*[+/]+\s*\d+\s*[gt]b?|\d+\s*[gt]b?)$',
        '',
        name,
        flags=re.IGNORECASE,
    )
    name = name.replace('()', '')
    name = re.sub(r'\s+', '', name)
    # 统一品牌名：中文→英文（以 ZOL 命名为准）
    brand_map = {
        '华为': 'huawei', '荣耀': 'honor', '小米': 'xiaomi', '红米': 'redmi',
        '一加': 'oneplus', '真我': 'realme', '三星': 'samsung', '苹果': 'apple',
        '努比亚': 'nubia', '摩托罗拉': 'motorola', '魅族': 'meizu',
        '联想': 'lenovo', '索尼': 'sony', '谷歌': 'google', '中兴': 'zte',
        '华硕': 'asus', '诺基亚': 'nokia', '夏普': 'sharp',
        '步步高': 'vivo', 'vivo': 'vivo', 'oppo': 'oppo', 'iqoo': 'iqoo', 'poco': 'xiaomi',
    }
    for cn, en in brand_map.items():
        if name.startswith(cn):
            name = en + name[len(cn):]
            break
    # 去除常见后缀
    for suffix in ['5g版', '4g版', '5g', '4g', 'wifi版', '全网通', 'wifi']:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    # 去除末尾多余分隔符
    name = name.rstrip('/-_')
    return name


def fuzzy_model_key(row):
    """更激进的模糊匹配键"""
    key = model_key(row)
    if not key:
        return ''
    key = re.sub(r'[（(].*?[）)]', '', key)
    key = key.replace('.', '').replace('-', '')
    return key


def model_storage_signature(row):
    raw_name = str(row.get('型号') or row.get('name') or '')
    name = raw_name.replace('（', '(').replace('）', ')')
    values = []

    def append_amount(amount, unit='gb'):
        values.append(int(amount) * (1024 if unit and unit.lower().startswith('t') else 1))

    candidates = re.findall(r'\(([^)]*)\)', name)
    candidates.append(name)
    if not any(re.search(r'(?:gb|tb|\d+\s*[+/]+\s*\d+\s*[gt]b?)', item, re.IGNORECASE) for item in candidates):
        field_capacity = ' '.join(str(row.get(field, '') or '') for field in ('内存', '存储')).strip()
        if field_capacity:
            candidates.append(field_capacity)

    for group in candidates:
        normalized = re.sub(r'\(\)', '', group)
        pair = re.search(r'(\d+)\s*(?:gb)?\s*[+/]+\s*(\d+)\s*([gt]b?)', normalized, re.IGNORECASE)
        if pair:
            append_amount(pair.group(1), 'gb')
            append_amount(pair.group(2), pair.group(3))
            break
        amounts = re.findall(r'(\d+)\s*([gt]b?)', normalized, re.IGNORECASE)
        if amounts:
            for amount, unit in amounts[:2]:
                append_amount(amount, unit)
            break
    return tuple(values)



def brand_model_sort_key(row):
    brand = normalize_brand(row.get('品牌') or derive_brand_from_name(row.get('型号', '')))
    model = model_key(row) or re.sub(r'\s+', '', str(row.get('型号') or row.get('name') or '')).lower()
    return (brand.casefold(), model)


def source_match_sort_key(row):
    return brand_model_sort_key(row) + (model_storage_signature(row),)

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
    files = glob.glob(os.path.join(ROOT, pattern))
    if not files:
        files = glob.glob(os.path.join(ROOT, '**', pattern), recursive=True)
    if not files:
        return None
    data_files = [f for f in files if 'progress' not in f and 'manifest' not in f]
    if not data_files:
        data_files = files
    return max(data_files, key=os.path.getmtime)


def load_all(pattern, prefer_latest=False):
    """加载所有匹配文件并合并为去重列表（按手机ID去重）"""
    files = glob.glob(os.path.join(ROOT, pattern))
    if not files:
        files = glob.glob(os.path.join(ROOT, '**', pattern), recursive=True)
    data_files = [f for f in files if 'progress' not in f and 'manifest' not in f]
    if not data_files:
        data_files = files

    def data_file_key(path):
        basename = os.path.basename(path)
        matches = re.findall(r'(\d{8})', basename)
        crawl_date = matches[-1] if matches else ''
        canonical = not re.match(r'^\d+_', basename)
        return crawl_date, canonical, basename

    all_rows = []
    seen_positions = {}
    sort_key = data_file_key if prefer_latest else os.path.getmtime
    for path in sorted(data_files, key=sort_key):
        rows = load(path)
        for row in rows:
            phone_id = row.get('手机ID') or row.get('id') or row.get('型号', '') or row.get('name', '')
            key = str(phone_id).strip().lower().replace(' ', '')
            if key and key in seen_positions:
                if prefer_latest:
                    all_rows[seen_positions[key]] = row
                continue
            if key:
                seen_positions[key] = len(all_rows)
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

        raw_brand = row.get('品牌') or row.get('brand')
        if raw_brand:
            normalized['品牌'] = normalize_brand(raw_brand)
        
        if 'name' in row and '型号' not in normalized:
            normalized['型号'] = row['name']
        if 'id' in row and '手机ID' not in normalized:
            normalized['手机ID'] = row['id']

        model_name = normalized.get('型号', '')
        source_name = row.get('name', '')
        if model_name and source_name and not derive_brand_from_name(model_name):
            source_brand = derive_brand_from_name(source_name)
            compact_model = re.sub(r'\s+', '', str(model_name)).casefold()
            compact_source = re.sub(r'\s+', '', str(source_name)).casefold()
            if source_brand and compact_model and compact_model in compact_source:
                normalized['型号'] = clean_value(source_name)

        if not normalized.get('品牌') or normalized['品牌'] == '-':
            model_name = normalized.get('型号', row.get('name', ''))
            derived = derive_brand_from_name(model_name)
            if derived:
                normalized['品牌'] = normalize_brand(derived)

        for key, val in row.items():
            if key in FIXED or key in ['id', 'name', 'brand', 'url', 'crawl_time', 'param_url', 'phone_id']:
                continue
            unified = norm(key)
            if unified in normalized and normalized[unified] not in ('', '-'):
                value = clean_spec_value(unified, val)
                if value not in ('', '-') and value != normalized[unified]:
                    normalized[unified] = f"{normalized[unified]}|{value}"
            else:
                normalized[unified] = clean_spec_value(unified, val)

        add_derived_fields(normalized)

        out.append(normalized)
    return out


def merge_verified_rows(zol_rows, pconline_rows, all_fields):
    # 第一级索引: 精确匹配
    pconline_exact = {}
    # 第二级索引: 模糊匹配
    pconline_fuzzy = {}
    for row in sorted(pconline_rows, key=source_match_sort_key):
        exact = model_key(row)
        fuzzy = fuzzy_model_key(row)
        if exact:
            pconline_exact.setdefault(exact, []).append(row)
        if fuzzy and fuzzy != exact:
            pconline_fuzzy.setdefault(fuzzy, []).append(row)
    used_pconline = set()
    zol_exact_families = {model_key(row) for row in zol_rows if model_key(row)}
    zol_fuzzy_families = {fuzzy_model_key(row) for row in zol_rows if fuzzy_model_key(row)}

    def has_family_match(row, exact_families, fuzzy_families):
        exact = model_key(row)
        fuzzy = fuzzy_model_key(row)
        return bool(
            (exact and exact in exact_families)
            or (fuzzy and fuzzy in fuzzy_families)
        )

    def row_identity(row):
        return (
            model_key(row),
            model_storage_signature(row),
            str(row.get('手机ID') or row.get('id') or row.get('型号') or row.get('name') or ''),
        )

    def pick_matching_pconline(candidates, zol_row):
        if not candidates:
            return None
        available = [row for row in candidates if row_identity(row) not in used_pconline]
        if not available:
            return None
        zol_signature = model_storage_signature(zol_row)
        same_signature = [row for row in available if model_storage_signature(row) == zol_signature]
        if zol_signature:
            return same_signature[0] if len(same_signature) == 1 else None
        no_signature = [row for row in available if not model_storage_signature(row)]
        return no_signature[0] if len(no_signature) == 1 else None
    merged = []

    def combine_rows(zol_row, pconline_row):
        combined = {}
        differences = []
        # 跳过比较的字段（数据结构差异大，不适合语义比较）
        skip_compare_fields = {
            '摄像头参数', '前置视频', '后置视频', '摄像头特色', '其他摄像头参数',
            '传感器尺寸', '镜头片数', '焦距', '变焦倍数', '摄像头名称',
            '后置摄像头像素', '前置摄像头像素', '后置摄像头', '前置摄像头'
        }
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
            elif field == '型号' and (model_key(zol_row) == model_key(pconline_row) or fuzzy_model_key(zol_row) == fuzzy_model_key(pconline_row)):
                combined[field] = min([zol_val, pc_val], key=lambda value: len(str(value)))
            elif field in skip_compare_fields:
                # 结构差异字段，直接取 ZOL 值，不标记为差异
                combined[field] = zol_val
            elif semantic_value_equal(zol_val, pc_val):
                combined[field] = zol_val  # 优先保留简洁版（通常ZOL更规范）
            else:
                combined[field] = f"中关村在线: {zol_val} | 太平洋电脑网: {pc_val}"
                differences.append(f"{field}: 中关村在线={zol_val}; 太平洋电脑网={pc_val}")

        source_rows = {
            '中关村在线': zol_row,
            '太平洋电脑网': pconline_row,
        }
        status, validation_differences = classify_source_agreement(source_rows)
        combined['数据来源'] = '中关村在线+太平洋电脑网'
        combined['验证状态'] = status
        combined['交叉验证差异'] = validation_differences
        combined[SOURCE_VALIDATION_ROWS_FIELD] = source_rows
        return combined

    for zol_row in sorted(zol_rows, key=source_match_sort_key):
        key = model_key(zol_row)
        pconline_row = pick_matching_pconline(pconline_exact.get(key), zol_row)
        if not pconline_row:
            fuzzy = fuzzy_model_key(zol_row)
            pconline_row = pick_matching_pconline(pconline_fuzzy.get(fuzzy), zol_row)
        if pconline_row:
            used_pconline.add(row_identity(pconline_row))
            merged.append(combine_rows(zol_row, pconline_row))
            continue
        row = dict(zol_row)
        row['数据来源'] = '中关村在线'
        has_pconline_family = bool(
            pconline_exact.get(key)
            or pconline_fuzzy.get(fuzzy_model_key(zol_row))
        )
        row['验证状态'] = FAMILY_CONFIG_MISMATCH_STATUS if has_pconline_family else '单源'
        row['交叉验证差异'] = (
            FAMILY_CONFIG_MISMATCH_DIFFERENCE if has_pconline_family else '-'
        )
        row[SOURCE_VALIDATION_ROWS_FIELD] = {'中关村在线': zol_row}
        merged.append(row)

    for pconline_row in sorted(pconline_rows, key=source_match_sort_key):
        if row_identity(pconline_row) in used_pconline:
            continue
        row = dict(pconline_row)
        # 关键：单源记录也要品牌归一化
        if '品牌' in row:
            row['品牌'] = normalize_brand(row['品牌'])
        row['数据来源'] = '太平洋电脑网'
        has_zol_family = has_family_match(
            pconline_row, zol_exact_families, zol_fuzzy_families
        )
        row['验证状态'] = FAMILY_CONFIG_MISMATCH_STATUS if has_zol_family else '单源'
        row['交叉验证差异'] = (
            FAMILY_CONFIG_MISMATCH_DIFFERENCE if has_zol_family else '-'
        )
        row[SOURCE_VALIDATION_ROWS_FIELD] = {'太平洋电脑网': pconline_row}
        merged.append(row)

    return merged


def append_unique_single_source(base_rows, extra_rows, source):
    family_index = {}
    for index, row in enumerate(base_rows):
        family = model_key(row)
        if family:
            family_index.setdefault(family, []).append(index)
    appended = []
    matched = 0
    appended_keys = set()
    for extra_row in extra_rows:
        family = model_key(extra_row)
        signature = model_storage_signature(extra_row)
        candidates = family_index.get(family, [])
        same_variant = [
            index for index in candidates
            if model_storage_signature(base_rows[index]) == signature
        ]
        matched_index = same_variant[0] if len(same_variant) == 1 else None
        if matched_index is None and not signature:
            no_capacity = [index for index in candidates if not model_storage_signature(base_rows[index])]
            if len(no_capacity) == 1:
                matched_index = no_capacity[0]

        if matched_index is not None:
            row = base_rows[matched_index]
            sources = [item for item in str(row.get('数据来源', '')).split('+') if item]
            if source not in sources:
                sources.append(source)
                row['数据来源'] = '+'.join(sources)
            source_rows = dict(row.get(SOURCE_VALIDATION_ROWS_FIELD) or {})
            if not source_rows:
                source_rows = {name: row for name in sources if name != source}
            source_rows[source] = extra_row
            related_ids = {item.strip() for item in str(row.get('关联手机ID', '')).split('|') if item.strip()}
            for source_row in source_rows.values():
                source_id = str(source_row.get('手机ID') or source_row.get('id') or '').strip()
                if source_id:
                    related_ids.add(source_id)
            if related_ids:
                row['关联手机ID'] = '|'.join(sorted(related_ids))
            status, validation_differences = classify_source_agreement(source_rows)
            row['验证状态'] = status
            row['交叉验证差异'] = validation_differences
            row[SOURCE_VALIDATION_ROWS_FIELD] = source_rows
            matched += 1
            continue

        identity = str(extra_row.get('手机ID') or extra_row.get('id') or '').strip()
        if not identity:
            identity = re.sub(r'\s+', '', str(extra_row.get('型号') or extra_row.get('name') or '')).lower()
        if identity and identity in appended_keys:
            continue
        row = dict(extra_row)
        if '品牌' in row:
            row['品牌'] = normalize_brand(row['品牌'])
        row['数据来源'] = source
        row['验证状态'] = FAMILY_CONFIG_MISMATCH_STATUS if candidates else '单源'
        row['交叉验证差异'] = (
            FAMILY_CONFIG_MISMATCH_DIFFERENCE if candidates else '-'
        )
        row[SOURCE_VALIDATION_ROWS_FIELD] = {source: extra_row}
        appended.append(row)
        if identity:
            appended_keys.add(identity)
    return appended, matched


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

    zol_files = sorted(glob.glob(os.path.join(ROOT, "data/zol_phones_*.json")))
    pconline_files = sorted(glob.glob(os.path.join(ROOT, "data/pconline_phones_*.json")))
    cnmo_files = sorted(glob.glob(os.path.join(ROOT, "data/cnmo_phones_*.json")))
    print(f"中关村在线数据文件 ({len(zol_files)}): {[os.path.basename(f) for f in zol_files]}")
    print(f"太平洋电脑网数据文件 ({len(pconline_files)}): {[os.path.basename(f) for f in pconline_files]}")
    print(f"CNMO数据文件 ({len(cnmo_files)}): {[os.path.basename(f) for f in cnmo_files]}")

    zol_rows = guard_publish_rows(norm_rows(load_all("data/zol_phones_*.json"), '中关村在线'))
    pconline_rows = guard_publish_rows(norm_rows(load_all("data/pconline_phones_*.json"), '太平洋电脑网'))
    raw_cnmo_rows = norm_rows(load_all("data/cnmo_phones_*.json", prefer_latest=True), 'CNMO')
    cnmo_rows = guard_publish_rows(raw_cnmo_rows, source='CNMO')
    cnmo_future_count = sum(is_future_release(row) for row in raw_cnmo_rows)
    cnmo_low_quality_count = sum(
        not is_future_release(row) and is_low_quality_cnmo_single_source(row)
        for row in raw_cnmo_rows
    )
    print(
        f"发布防御丢弃: CNMO未来上市 {cnmo_future_count} 条，"
        f"低质量空壳 {cnmo_low_quality_count} 条；CNMO价格仅保留数值或空"
    )

    if not zol_rows and not pconline_rows and not cnmo_rows:
        print("错误: 没有找到任何数据文件")
        return
    if not zol_rows and not pconline_rows:
        print("错误: 仅找到 CNMO 数据，缺少 ZOL/PConline 主来源，拒绝生成发布数据")
        return

    source_rows = zol_rows + pconline_rows + cnmo_rows
    print(f"中关村在线:{len(zol_rows)} 太平洋电脑网:{len(pconline_rows)} CNMO:{len(cnmo_rows)} 合计:{len(source_rows)}")

    source_header = collect_fields(source_rows)
    all_rows = merge_verified_rows(zol_rows, pconline_rows, source_header)
    cnmo_appended, cnmo_matched = append_unique_single_source(all_rows, cnmo_rows, 'CNMO')
    cnmo_appended_in_scope = [row for row in cnmo_appended if is_cnmo_single_source_in_publish_scope(row)]
    cnmo_out_of_scope = len(cnmo_appended) - len(cnmo_appended_in_scope)
    all_rows.extend(cnmo_appended_in_scope)
    all_rows.sort(key=source_match_sort_key)
    for row in all_rows:
        row.pop(SOURCE_VALIDATION_ROWS_FIELD, None)
    before_final_guard = len(all_rows)
    all_rows = guard_publish_rows(all_rows)
    print(f"CNMO单源追加:{len(cnmo_appended_in_scope)} 范围外丢弃:{cnmo_out_of_scope} 来源覆盖匹配:{cnmo_matched}")
    print(f"最终发布防御再次丢弃未来上市: {before_final_guard - len(all_rows)} 条")
    header = collect_fields(all_rows)
    dual_source_count = sum(1 for row in all_rows if row.get('验证状态', '').startswith('双源'))
    print(f"交叉验证后机型:{len(all_rows)} 双源记录:{dual_source_count} 非双源记录:{len(all_rows) - dual_source_count}")

    merged_csv_path = os.path.join(ROOT, f"data/merged_phones_{today}.csv")
    merged_json_path = os.path.join(ROOT, f"data/merged_phones_{today}.json")
    write_csv(merged_csv_path, all_rows, header)
    write_json(merged_json_path, all_rows)

    diffs = []
    if zol_rows and pconline_rows:
        diffs = diff(zol_rows, pconline_rows, source_header)
        if diffs:
            diff_path = os.path.join(ROOT, f"data/diff_phones_{today}.csv")
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
