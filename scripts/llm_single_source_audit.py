#!/usr/bin/env python3
"""Call an AA 50+ LLM to analyze single-source root causes.

Reads the audit report + raw data sample, sends to a high-quality LLM
(AA Intelligence Index >= 50) and produces a markdown analysis.

Tries models in order of AA Index (highest first):
  1. Claude Opus 5 (max) - AA 61
  2. GPT-5.6 Sol (max) - AA 59
  3. Kimi K3 - AA 57
  4. GPT-5.6 Sol (high) - AA 56
  5. Grok 4.5 (high) - AA 54

Usage:
    python3 scripts/llm_single_source_audit.py --data ./data/latest.json --report ./audit_report.json --output ./llm_analysis.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path


# AA 50+ models ranked by Intelligence Index, with API config
AA_MODELS = [
    {
        "name": "Claude Opus 5 (max)",
        "aa_index": 61,
        "provider": "anthropic",
        "model": "claude-opus-5-20250115",
        "max_tokens": 16000,
        "env_keys": ["ANTHROPIC_API_KEY"],
        "endpoint": "https://api.anthropic.com/v1/messages",
    },
    {
        "name": "GPT-5.6 Sol (max)",
        "aa_index": 59,
        "provider": "openai",
        "model": "gpt-5.6-sol",
        "max_tokens": 16000,
        "env_keys": ["OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ZEN_API_KEY"],
        "endpoint": "https://api.openai.com/v1/chat/completions",
    },
    {
        "name": "DeepSeek V4 Flash 0731 (max)",
        "aa_index": 50,
        "provider": "nvidia-nim",
        "model": "deepseek-ai/deepseek-v4-flash",
        "max_tokens": 12000,
        "env_keys": ["NVIDIA_NIM_API_KEY"],
        "endpoint": "https://integrate.api.nvidia.com/v1/chat/completions",
    },
    {
        "name": "Kimi K3",
        "aa_index": 57,
        "provider": "kimi",
        "model": "k3",
        "max_tokens": 12000,
        "env_keys": ["KIMI_API_KEY", "MOONSHOT_API_KEY", "KIMI_CODINGPLAN_API_KEY"],
        "endpoint": "https://api.moonshot.cn/v1/chat/completions",
    },
    {
        "name": "GPT-5.6 Sol (high)",
        "aa_index": 56,
        "provider": "openai",
        "model": "gpt-5.6-sol",
        "max_tokens": 8000,
        "env_keys": ["OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ZEN_API_KEY"],
        "endpoint": "https://api.openai.com/v1/chat/completions",
    },
    {
        "name": "Grok 4.5 (high)",
        "aa_index": 54,
        "provider": "xai",
        "model": "grok-4.5",
        "max_tokens": 8000,
        "env_keys": ["XAI_API_KEY"],
        "endpoint": "https://api.x.ai/v1/chat/completions",
    },
]


def build_prompt(report: dict, data_sample: list[dict]) -> str:
    """Build analysis prompt from audit report + data sample."""
    src_dist = report.get("source_distribution", {})
    causes = report.get("causes", {})
    detail = report.get("detail", {})

    # Build top single-source series/products summary
    top_single = detail.get("top_single_series", detail.get("top_single_products", []))[:15]
    top_text = "\n".join(
        f"  - {item.get('series', item.get('product', '?'))}: {item.get('source', '?')} ({item.get('rows', 0)} rows)"
        for item in top_single
    )

    return f"""# 单源数据根因分析任务

你是一个数据质量分析专家。请分析以下爬虫数据的单源（single-source）问题，找出为什么很多条目只来自一个数据源。

## 数据概览
- 总行数: {report['total']}
- 多源行数: {report['multi_count']} ({report['multi_rate']}%)
- 单源行数: {report['single_count']} ({report['single_rate']}%)

## 数据源分布
{json.dumps(src_dist, ensure_ascii=False, indent=2)}

## 根因概要
{json.dumps(causes, ensure_ascii=False, indent=2)}

## 单源条目 Top 15
{top_text}

## 数据样本（前5行）
{json.dumps(data_sample[:5], ensure_ascii=False, indent=2, default=str)}

## 分析要求

请用中文输出以下内容：

### 1. 单源根因分类
对每个根因类别，说明：
- 具体原因
- 影响行数
- 修复建议（如果是代码可修的，指出具体修改方向）

### 2. 数据源覆盖分析
- 哪些数据源覆盖了哪些品牌/系列
- 哪些品牌/系列在多个源中都有但没被合并
- 哪些品牌/系列只有一个源有

### 3. 合并匹配改进建议
- 当前合并逻辑可能有什么问题
- 如何改进 trim/车型级匹配
- 是否需要增加新的爬取源

### 4. 优先级行动清单
按影响大小排序列出需要修复的问题，格式：
- [P0/P1/P2] 问题描述 → 修复方向 → 预期影响

### 5. 多源率提升路径
- 当前多源率: {report['multi_rate']}%
- 可达到的多源率: X% （说明依据）
- 达到80-90%多源率需要什么条件
"""


def _first_key(model: dict) -> str | None:
    """Return first available API key from candidate env var names."""
    for name in model.get("env_keys", []):
        val = os.environ.get(name)
        if val:
            return val
    return None


def call_openai_compatible(model: dict, prompt: str) -> str | None:
    """Call OpenAI-compatible API (OpenAI, Kimi, xAI)."""
    key = _first_key(model)
    if not key:
        return None
    body = json.dumps({
        "model": model["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": model["max_tokens"],
        "temperature": 0.7,
    }).encode("utf-8")
    req = urllib.request.Request(
        model["endpoint"],
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"  {model['name']} failed: {exc}", file=sys.stderr)
        return None


def call_anthropic(model: dict, prompt: str) -> str | None:
    """Call Anthropic API."""
    key = _first_key(model)
    if not key:
        return None
    body = json.dumps({
        "model": model["model"],
        "max_tokens": model["max_tokens"],
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        model["endpoint"],
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["content"][0]["text"]
    except Exception as exc:
        print(f"  {model['name']} failed: {exc}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(description="LLM single-source audit")
    parser.add_argument("--data", required=True, help="Path to latest.json")
    parser.add_argument("--report", required=True, help="Path to audit report JSON")
    parser.add_argument("--output", required=True, help="Output markdown path")
    args = parser.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        rows = data["items"]
    elif isinstance(data, dict) and "data" in data:
        rows = data["data"]
    elif isinstance(data, list):
        rows = data
    else:
        rows = []

    prompt = build_prompt(report, rows[:50])

    print("Trying AA 50+ models in order of Intelligence Index...")
    for model in AA_MODELS:
        print(f"  Trying {model['name']} (AA {model['aa_index']})...")
        if model["provider"] == "anthropic":
            result = call_anthropic(model, prompt)
        else:
            result = call_openai_compatible(model, prompt)
        if result:
            Path(args.output).write_text(result, encoding="utf-8")
            print(f"Analysis from {model['name']} written to {args.output}")
            return
        else:
            print(f"  {model['name']} unavailable, trying next...")

    # No LLM available - write deterministic analysis
    fallback = f"""# 单源数据根因分析（确定性降级报告）

> 未配额AA 50+大模型API，以下为确定性分析。

## 数据概览
- 总行数: {report['total']}
- 多源: {report['multi_count']} ({report['multi_rate']}%)
- 单源: {report['single_count']} ({report['single_rate']}%)

## 根因分类
1. **车系仅单源**: {report['causes'].get('series_only_single', 0)} 行（对端未爬到该系列）
2. **trim级合并gap**: {report['causes'].get('trim_merge_gap', 0)} 行（系列有双源但具体车型未匹配）

## 数据源分布
{json.dumps(report.get('source_distribution', {}), ensure_ascii=False, indent=2)}

## Top 单源系列
{json.dumps(report.get('detail', {}).get('top_single_series', report.get('detail', {}).get('top_single_products', []))[:20], ensure_ascii=False, indent=2)}
"""
    Path(args.output).write_text(fallback, encoding="utf-8")
    print(f"No LLM available - deterministic fallback written to {args.output}")


if __name__ == "__main__":
    main()
