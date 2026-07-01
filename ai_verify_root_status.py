#!/usr/bin/env python3
"""
AI 联网验证手机 root/越狱状态，智能增量 + 品牌SOC漏洞匹配。

策略：
1. 加载已合并数据，跳过已有明确状态（非"未知"）的机型
2. 按品牌+SOC分组，先查跨型号漏洞模式（如 "小米 骁龙8Gen3 → Magisk 可用"）
3. 无匹配漏洞的机型单独查询
4. 累积结果到 root_status.json 缓存，下次增量跳过

API：优先 NIM free (nvidia/nvidia-glm-5.1)，备用 OpenRouter free

字段命名：
  安卓：不可root / 可临时root（重启失效）/ 可永久root（方法）
  iPhone：不可越狱 / 可完美越狱（工具版本） / 可不完美越狱（工具版本）
"""

import json
import os
import sys
import re
import time
import hashlib
import concurrent.futures
import threading
from datetime import datetime
from collections import defaultdict
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ── 常量 ──────────────────────────────────────────────
DATA_FILE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "merged_phones_20260626.json")
CACHE_FILE = os.path.join(os.path.dirname(__file__), "root_status_cache.json")
OUTPUT_FILE = DATA_FILE  # 原地更新

# 每批品牌SOC查询多少个型号（避免prompt过长）
MAX_BATCH = 8

# ── 性能优化配置 ──────────────────────────────────────
MAX_TOKENS = 300
API_TIMEOUT = 30
MAX_RETRIES = 3
MAX_WORKERS = 2  # 并发请求数（保守：最多 2 个网络 worker）
TOTAL_TIME_BUDGET = 25 * 60  # 25 分钟总时间预算
# 请求级 rate limiting：每秒最多发起 2 个请求
MIN_REQUEST_INTERVAL = 0.5  # 秒
_last_request_time = 0.0
_request_lock = threading.Lock()

# ── API ──────────────────────────────────────────────
NIM_KEY = os.environ.get("NVIDIA_NIM_API_KEY", "")
OR_KEY = os.environ.get("OPENROUTER_API_KEY", "")


def ai_query(prompt, model=None, retries=MAX_RETRIES):
    """调用 AI 查询，自动 fallback NIM → OpenRouter"""
    # Rate limiting: 请求发起前等待
    global _last_request_time
    with _request_lock:
        now = time.time()
        wait = MIN_REQUEST_INTERVAL - (now - _last_request_time)
        if wait > 0:
            time.sleep(wait)
        _last_request_time = time.time()

    # NIM 优先（免费）
    if NIM_KEY:
        try:
            req = Request(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                data=json.dumps({
                    "model": model or "nvidia/nvidia-glm-5.1",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": MAX_TOKENS,
                    "temperature": 0.1,
                }).encode(),
                headers={
                    "Authorization": f"Bearer {NIM_KEY}",
                    "Content-Type": "application/json",
                },
            )
            resp = urlopen(req, timeout=API_TIMEOUT)
            body = json.loads(resp.read())
            return body["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"  NIM error: {e}", file=sys.stderr)

    # OpenRouter 备用
    if OR_KEY:
        for attempt in range(retries):
            try:
                req = Request(
                    "https://openrouter.ai/api/v1/chat/completions",
                    data=json.dumps({
                        "model": "google/gemma-4-31b-it:free",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": MAX_TOKENS,
                        "temperature": 0.1,
                    }).encode(),
                    headers={
                        "Authorization": f"Bearer {OR_KEY}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://phones.jiucai.eu.org",
                        "X-Title": "Phone Root Status Verifier",
                    },
                )
                resp = urlopen(req, timeout=API_TIMEOUT)
                body = json.loads(resp.read())
                return body["choices"][0]["message"]["content"].strip()
            except Exception as e:
                print(f"  OR error (attempt {attempt+1}): {e}", file=sys.stderr)
                time.sleep(2 ** attempt)

    return None


def parse_ai_response(text, brand, soc, model_name):
    """解析 AI 返回的 root/越狱状态为结构化数据"""
    text_lower = text.lower()

    # iPhone 判断
    if brand and "苹果" in str(brand):
        if "完美越狱" in text or "untethered" in text_lower:
            tool = re.search(r'(?:工具|tool)[：:]\s*([^\n,，]+)', text)
            return f"可完美越狱（{tool.group(1)}）" if tool else "可完美越狱"
        if "不完美越狱" in text or "semi-tethered" in text_lower or "semi-untethered" in text_lower:
            tool = re.search(r'(?:工具|tool)[：:]\s*([^\n,，]+)', text)
            return f"可不完美越狱（{tool.group(1)}）" if tool else "可不完美越狱"
        if "不可越狱" in text or "no jailbreak" in text_lower or "无法越狱" in text:
            return "不可越狱"
        return "未知"

    # Android 判断
    if "永久root" in text or "permanent" in text_lower:
        method = re.search(r'(?:方法|method|工具|tool)[：:]\s*([^\n,，]+)', text)
        return f"可永久root（{method.group(1)}）" if method else "可永久root"
    if "临时root" in text or "temporary" in text_lower or "重启失效" in text:
        method = re.search(r'(?:方法|method|工具|tool)[：:]\s*([^\n,，]+)', text)
        return f"可临时root（{method.group(1)}）" if method else "可临时root（重启失效）"
    if "不可root" in text or "no root" in text_lower or "无法root" in text or "不能root" in text:
        return "不可root"
    return "未知"


# ── 缓存 ──────────────────────────────────────────────
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f"缓存已保存: {len(cache)} 条")


# ── 核心逻辑 ──────────────────────────────────────────
def extract_soc(row):
    """从处理器字段提取 SOC 型号"""
    proc = row.get("处理器", "") or row.get("CPU", "") or row.get("cpu", "")
    # 提取关键 SOC 型号
    soc = ""
    m = re.search(r'(骁龙|Snapdragon)\s*(\d+)\s*(Gen\s*\d+)?', proc, re.I)
    if m:
        soc = f"骁龙{m.group(2)}{m.group(3) or ''}"
    m = re.search(r'(天玑|Dimensity)\s*(\d+)', proc, re.I)
    if m:
        soc = f"天玑{m.group(2)}"
    m = re.search(r'(麒麟|Kirin)\s*(\d+)', proc, re.I)
    if m:
        soc = f"麒麟{m.group(2)}"
    m = re.search(r'(Exynos|猎户座)\s*(\d+)', proc, re.I)
    if m:
        soc = f"Exynos{m.group(2)}"
    m = re.search(r'(A\d+)\s*(Bionic|仿生)?', proc, re.I)
    if m:
        soc = m.group(1)
    return soc.strip() if soc else "未知SOC"


def verify_brand_soc_group(brand, soc, models, os_info):
    """查询某个品牌+SOC组合的通用 root/越狱漏洞"""
    model_list = ", ".join(models[:MAX_BATCH])
    prompt = f"""你是手机 root/越狱 数据库专家。请根据你的训练知识（截止2026年中的信息），回答以下问题——无需联网搜索，用你已有的知识即可。

品牌：{brand}
SOC/处理器：{soc}
操作系统：{os_info or 'Android'}
代表型号：{model_list}

请回答：
1. 该品牌该SOC的机型，是否普遍可通过Magisk/APatch等方式获取root权限？
   - 如果可以，是永久root还是临时root（重启失效）？
   - 具体用什么方法/工具？
2. 如果是iPhone，是否可越狱？完美还是不完美？用什么工具版本？

请按以下格式回答（每行一个结论）：
结论：可永久root / 可临时root / 不可root / 可完美越狱 / 可不完美越狱 / 不可越狱 / 不确定
方法：[具体方法名称，如 Magisk、checkra1n、unc0ver 等]
说明：[简短说明]"""

    print(f"  AI 查询: {brand} {soc} ({len(models)} 机型)...")
    resp = ai_query(prompt)
    if not resp:
        return None

    result = {"brand": brand, "soc": soc, "models": models, "raw": resp}
    # 解析结论
    for line in resp.split("\n"):
        if line.startswith("结论："):
            result["conclusion"] = line.replace("结论：", "").strip()
        if line.startswith("方法："):
            result["method"] = line.replace("方法：", "").strip()
    return result


def verify_single_model(row):
    """查询单个机型的 root/越狱状态"""
    model = row.get("型号", "") or row.get("name", "")
    brand = row.get("品牌", "")
    soc = extract_soc(row)
    os_ver = row.get("操作系统", "") or row.get("系统", "")

    prompt = f"""你是手机 root/越狱 数据库专家。请根据训练知识回答——无需联网搜索。

机型：{model}
品牌：{brand}
处理器：{soc}
操作系统：{os_ver}

该机型是否可以root（安卓）或越狱（iPhone）？
- 安卓：是否可通过Magisk等方式获取root？永久还是临时（重启失效）？
- iPhone：是否可越狱？完美（重启不失效）还是不完美？用什么工具？

请按格式回答：
结论：可永久root / 可临时root / 不可root / 可完美越狱 / 可不完美越狱 / 不可越狱 / 不确定
方法：[工具名称]
说明：[简短说明]"""

    print(f"  AI 查询单机型: {brand} {model[:40]}...")
    resp = ai_query(prompt)
    if not resp:
        return None
    return resp


# ── 主流程 ──────────────────────────────────────────────
def main():
    print(f"=== AI root/越狱 验证 ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"数据: {DATA_FILE}")

    # 加载数据
    with open(DATA_FILE) as f:
        rows = json.load(f)
    print(f"总机型: {len(rows)}")

    # 加载缓存
    cache = load_cache()

    # 需要验证的机型
    pending = []
    already_verified = 0
    for row in rows:
        key = (row.get("型号", "") or row.get("name", "")).strip()
        if not key:
            continue
        current = row.get("root或越狱", row.get("是否可root", "未知"))
        # 跳过已有明确状态的
        if current not in ("未知", "", None, "-"):
            already_verified += 1
            continue
        # 检查缓存
        if key in cache:
            row["root或越狱"] = cache[key]
            already_verified += 1
            continue
        pending.append(row)

    print(f"已有状态: {already_verified}")
    print(f"待验证: {len(pending)}")

    if not pending:
        print("✅ 全部已验证，无需AI查询")
        return

    # 按品牌+SOC分组
    groups = defaultdict(list)
    for row in pending:
        brand = row.get("品牌", "未知")
        soc = extract_soc(row)
        key = f"{brand}|{soc}"
        groups[key].append(row)

    # 先处理品牌+SOC组（跨型号漏洞）
    verified_count = 0
    start_time = time.time()

    # 并发处理品牌+SOC组
    def process_group(grp_key, grp_rows):
        if not grp_rows:
            return None
        brand, soc = grp_key.split("|", 1)
        models = [r.get("型号", "") or r.get("name", "") for r in grp_rows[:MAX_BATCH]]
        os_info = grp_rows[0].get("操作系统", "") if grp_rows else ""

        # 跳过无意义的SOC
        if soc in ("未知SOC", ""):
            return None

        result = verify_brand_soc_group(brand, soc, models, os_info)
        if not result or "不确定" in result.get("conclusion", ""):
            return None
        return (grp_key, grp_rows, result)

    # 使用线程池并发处理 —— 手动管理 shutdown 以便超时时取消 pending futures
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        future_to_key = {
            executor.submit(process_group, grp_key, grp_rows): grp_key
            for grp_key, grp_rows in sorted(groups.items())
        }

        for future in concurrent.futures.as_completed(future_to_key):
            # 检查时间预算
            if time.time() - start_time > TOTAL_TIME_BUDGET:
                print(f"⚠ 时间预算耗尽 ({TOTAL_TIME_BUDGET//60}分钟)，停止品牌SOC组查询并取消剩余任务")
                # 取消所有未完成的 future
                for f in future_to_key:
                    if not f.done():
                        f.cancel()
                break

            # future.result(timeout=...) 防止已在运行的 future 超时后仍阻塞
            remaining_time = TOTAL_TIME_BUDGET - (time.time() - start_time)
            if remaining_time <= 30:
                print(f"⚠ 剩余时间不足 ({remaining_time:.0f}s)，停止品牌SOC组查询")
                for f in future_to_key:
                    if not f.done():
                        f.cancel()
                break

            try:
                result = future.result(timeout=min(remaining_time, 90))
            except concurrent.futures.TimeoutError:
                print("⚠ 品牌SOC组任务超时，取消剩余并退出")
                for f in future_to_key:
                    if not f.done():
                        f.cancel()
                break

            if result is None:
                continue

            grp_key, grp_rows, group_result = result
            brand, soc = grp_key.split("|", 1)

            conclusion = group_result.get("conclusion", "未知")
            method = group_result.get("method", "")
            status = f"{conclusion}"
            if method and conclusion not in ("不可root", "不可越狱", "未知"):
                status += f"（{method}）"

            for row in grp_rows:
                row["root或越狱"] = status
                key = (row.get("型号", "") or row.get("name", "")).strip()
                cache[key] = status
                verified_count += 1

            print(f"  ✅ {brand} {soc}: {len(grp_rows)} 机型 → {status}")
            time.sleep(0.5)  # 轻微延迟避免 rate limit
    finally:
        # 关键：shutdown(wait=False) 立即返回，不等待已取消/运行中的 futures
        # cancel_futures=True 需要 Python 3.9+，GitHub Actions runner 使用 Python 3.12
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            # 兼容旧版本：仅 wait=False
            executor.shutdown(wait=False)

    # 处理剩余未匹配的单个机型
    remaining = [r for r in pending if r.get("root或越狱") in ("未知", "", None)]
    print(f"\n品牌SOC匹配后剩余: {len(remaining)} 个")

    # 并发处理单机型
    def process_single(row):
        resp = verify_single_model(row)
        if not resp:
            return None
        status = parse_ai_response(resp, row.get("品牌"), extract_soc(row), row.get("型号"))
        key = (row.get("型号", "") or row.get("name", "")).strip()
        return (row, key, status)

    # 使用线程池并发处理 —— 手动管理 shutdown 以便超时时取消 pending futures
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        future_to_row = {executor.submit(process_single, row): row for row in remaining}

        for future in concurrent.futures.as_completed(future_to_row):
            # 检查时间预算
            if time.time() - start_time > TOTAL_TIME_BUDGET:
                print(f"⚠ 时间预算耗尽 ({TOTAL_TIME_BUDGET//60}分钟)，停止单机型查询并取消剩余任务")
                # 取消所有未完成的 future
                for f in future_to_row:
                    if not f.done():
                        f.cancel()
                break

            # future.result(timeout=...) 防止已在运行的 future 超时后仍阻塞
            # 计算剩余时间预算，留 30s 缓冲
            remaining_time = TOTAL_TIME_BUDGET - (time.time() - start_time)
            if remaining_time <= 30:
                print(f"⚠ 剩余时间不足 ({remaining_time:.0f}s)，停止单机型查询")
                for f in future_to_row:
                    if not f.done():
                        f.cancel()
                break

            try:
                result = future.result(timeout=min(remaining_time, 60))
            except concurrent.futures.TimeoutError:
                print("⚠ 单任务超时，取消剩余并退出")
                for f in future_to_row:
                    if not f.done():
                        f.cancel()
                break

            if result is None:
                continue

            row, key, status = result
            row["root或越狱"] = status
            cache[key] = status
            verified_count += 1
            print(f"  ✅ {row.get('品牌', '?')} {key[:40]}: {status}")
            time.sleep(0.2)  # 极小延迟
    finally:
        # 关键：shutdown(wait=False) 立即返回，不等待已取消/运行中的 futures
        # cancel_futures=True 需要 Python 3.9+，GitHub Actions runner 使用 Python 3.12
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            # 兼容旧版本：仅 wait=False
            executor.shutdown(wait=False)

    # 标记仍未确定的
    for row in pending:
        if row.get("root或越狱") in ("未知", "", None):
            row["root或越狱"] = "未知"

    # 清理旧字段
    for row in rows:
        row.pop("是否可root", None)
        row.pop("root方案", None)
        row.pop("风险等级", None)

    # 保存
    with open(OUTPUT_FILE, "w") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 数据已保存: {OUTPUT_FILE}")

    save_cache(cache)
    print(f"本次验证: {verified_count} 机型")
    print(f"数据总行: {len(rows)}")


if __name__ == "__main__":
    main()
