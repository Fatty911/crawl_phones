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
import re
import subprocess
import sys
import urllib.request
from pathlib import Path


# AA 50+ models ranked by Intelligence Index, with API config
AA_MODELS = [
    {
        "name": "DeepSeek V4 Flash 0731 (max)",
        "aa_index": 50,
        "provider": "nvidia-nim",
        "model": "deepseek-ai/deepseek-v4-flash",
        "max_tokens": 4000,
        "env_keys": ["NVIDIA_NIM_API_KEY"],
        "endpoint": "https://integrate.api.nvidia.com/v1/chat/completions",
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


def _call_via_opencode(model: dict, prompt: str) -> str | None:
    """通过 OpenCode CLI（Agent 工具）调用模型，禁止直连模型 API。

    The provider key is consumed only by the OpenCode process; this function
    never issues HTTP requests to a model endpoint.
    """
    key = _first_key(model)
    if not key:
        return None
    endpoint = str(model.get("endpoint") or "").rstrip("/")
    if endpoint.endswith("/chat/completions"):
        endpoint = endpoint[: -len("/chat/completions")]
    if endpoint.endswith("/v1/messages"):
        endpoint = endpoint[: -len("/v1/messages")]
    provider_label = re.sub(r"[^A-Za-z0-9_-]", "-", str(model.get("name") or "provider").lower())[:60]
    is_anthropic = str(model.get("provider") or "").lower() == "anthropic"
    read_only = {
        "*": "deny",
        "read": "allow",
        "edit": "deny",
        "bash": "deny",
        "webfetch": "deny",
        "task": "deny",
        "question": "deny",
        "external_directory": "deny",
    }
    config = {
        "provider": {
            provider_label: {
                "npm": "@ai-sdk/anthropic" if is_anthropic else "@ai-sdk/openai-compatible",
                "name": provider_label,
                "options": {"baseURL": endpoint, "apiKey": f"{{env:{model['env_keys'][0]}}}"},
                "models": {model["model"]: {"limit": {"context": 131072, "output": int(model.get("max_tokens") or 8000)}}},
            }
        },
        "agent": {"plan": {"permission": read_only}},
        "permission": read_only,
    }
    env = dict(os.environ)
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config, ensure_ascii=False)
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    env["OPENCODE_DISABLE_TELEMETRY"] = "1"
    opencode_bin = os.environ.get("OPENCODE_BIN", "opencode")
    import tempfile
    try:
        with tempfile.TemporaryDirectory(prefix="audit-llm-") as tmpdir:
            prompt_path = os.path.join(tmpdir, "prompt.md")
            with open(prompt_path, "w", encoding="utf-8") as handle:
                handle.write(prompt)
            cmd = [
                opencode_bin, "run", "--pure", "--agent", "plan",
                "--model", f"{provider_label}/{model['model']}",
                "--format", "default",
                "--dir", tmpdir,
                "--file", "prompt.md",
                "Answer the attached prompt directly. Do not call tools or modify files. Return only the requested analysis.",
            ]
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
    except Exception as exc:
        print(f"  {model['name']} opencode call failed: {type(exc).__name__}", file=sys.stderr)
        return None
    if completed.returncode != 0:
        print(f"  {model['name']} opencode exit {completed.returncode}: {(completed.stderr or '')[:200]}", file=sys.stderr)
        return None
    content = (completed.stdout or "").strip()
    return content or None


def call_openai_compatible(model: dict, prompt: str) -> str | None:
    """通过 OpenCode CLI（Agent 工具）调用 OpenAI-compatible 端点。"""
    return _call_via_opencode(model, prompt)


def call_anthropic(model: dict, prompt: str) -> str | None:
    """通过 OpenCode CLI（Agent 工具）调用 Anthropic 端点。"""
    return _call_via_opencode(model, prompt)


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
