#!/usr/bin/env python3
"""AI 端点池（唯一事实源）：免费 → 单家 Plan → 聚合 Plan → 便宜按量付费，自动切换。

用户费用策略（全局）：免费端点优先，其次单家 Plan、聚合 Plan、便宜按量、中等按量、昂贵按量。
多端多仓库同步：本文件为唯一事实源，crawl_* 各仓库 / 本机 / VPS 保持一致（改这里后同步各处）。

端点说明：
- nvidia-nim：NVIDIA 免费端点（deepseek-ai/deepseek-v4-flash-0731），runner IP 有 529 风控需重试，
  免费层偶发输出退化（垃圾文本包围 JSON）——调用方需鲁棒解析。
- zenmux-free：ZenMux 免费层（deepseek-v4-flash-free），从 runner 被 Cloudflare 403，需走 DMIT 代理；
  key 按模型授权（403 access_denied 说明未授权该模型，探测会失败并自动切下一端点）。
- volcengine-coding：火山 CodingPlan（单家 Plan），key 名 VOLCENGINE_CODING_PLAN_API_KEY，
  端点 https://ark.cn-beijing.volces.com/api/coding/v3（套餐分离铁律：不是 /api/v3）。
- opencode-go：OpenCode Go 月订阅（聚合 Plan，$10/月），只启用 deepseek-v4-flash。
- zenmux：ZenMux 按量付费层（deepseek-v4-flash），需 DMIT 代理。
- deepseek-api：DeepSeek 官方按量（deepseek-chat），402 余额不足时探测失败自动跳过。

调用约定：
  import ai_providers
  for p in ai_providers.PROVIDERS: ...  # 顺序即优先级
  ai_providers.build_opencode_config(providers, max_tokens)  # 生成 opencode provider 配置
  ai_providers.apply_proxy_env(env, p, proxy_url)            # 按端点需求设置代理环境变量
"""

from __future__ import annotations

import json
from typing import Any

PROVIDERS: list[dict[str, Any]] = [
    # ── 免费层 ──────────────────────────────────────────────
    {
        "name": "nvidia-nim",
        "base": "https://integrate.api.nvidia.com/v1",
        "key_env": "NVIDIA_NIM_API_KEY",
        "model": "deepseek-ai/deepseek-v4-flash-0731",
        "use_proxy": False,
        "tier": "free",
    },
    {
        "name": "zenmux-free",
        "base": "https://zenmux.ai/api/v1",
        "key_env": "ZENMUX_API_KEY",
        "model": "deepseek-v4-flash-free",
        "use_proxy": True,
        "tier": "free",
    },
    # ── 单家 Plan 层 ────────────────────────────────────────
    {
        "name": "volcengine-coding",
        "base": "https://ark.cn-beijing.volces.com/api/coding/v3",
        "key_env": "VOLCENGINE_CODING_PLAN_API_KEY",
        "model": "deepseek-v4-flash",
        "use_proxy": False,
        "tier": "plan",
    },
    # ── 聚合 Plan 层 ────────────────────────────────────────
    {
        "name": "opencode-go",
        "base": "https://opencode.ai/zen/go/v1",
        "key_env": "OPENCODE_API_KEY",
        "model": "deepseek-v4-flash",
        "use_proxy": False,
        "tier": "plan",
    },
    # ── 按量付费层（便宜）──────────────────────────────────
    {
        "name": "zenmux",
        "base": "https://zenmux.ai/api/v1",
        "key_env": "ZENMUX_API_KEY",
        "model": "deepseek-v4-flash",
        "use_proxy": True,
        "tier": "payg",
    },
    {
        "name": "deepseek-api",
        "base": "https://api.deepseek.com/v1",
        "key_env": "DEEPSEEK_API_KEY",
        "model": "deepseek-chat",
        "use_proxy": False,
        "tier": "payg",
    },
]


def available(env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """过滤掉 key 未配置的端点（env 为 None 时用 os.environ）。"""
    import os

    env = env if env is not None else os.environ
    return [p for p in PROVIDERS if env.get(p["key_env"], "").strip()]


def build_opencode_config(providers: list[dict[str, Any]], max_tokens: int = 8000) -> dict[str, Any]:
    """为 opencode CLI 生成 provider 配置（@ai-sdk/openai-compatible 通用）。"""
    read_only = {
        "*": "deny", "read": "allow", "edit": "deny", "bash": "deny",
        "webfetch": "deny", "task": "deny", "question": "deny", "external_directory": "deny",
    }
    config = {
        "provider": {
            p["name"]: {
                "npm": "@ai-sdk/openai-compatible",
                "name": p["name"],
                "options": {"baseURL": p["base"], "apiKey": "{env:%s}" % p["key_env"]},
                "models": {p["model"]: {"limit": {"context": 1000000, "output": max(1024, max_tokens)}}},
            }
            for p in providers
        },
        "agent": {"plan": {"permission": read_only}},
        "permission": read_only,
    }
    return config


def apply_proxy_env(env: dict[str, str], provider: dict[str, Any], proxy_url: str) -> dict[str, str]:
    """按端点需求设置代理环境变量（zenmux 系需要 DMIT 代理绕过 Cloudflare 403）。"""
    run_env = dict(env)
    if provider.get("use_proxy") and proxy_url:
        run_env["NODE_USE_ENV_PROXY"] = "1"
        run_env["HTTPS_PROXY"] = proxy_url
        run_env["HTTP_PROXY"] = proxy_url
    else:
        run_env.pop("NODE_USE_ENV_PROXY", None)
        run_env.pop("HTTPS_PROXY", None)
        run_env.pop("HTTP_PROXY", None)
    return run_env


def probe_chat_ok(provider: dict[str, Any], proxy_url: str, key: str, timeout: int = 30) -> bool:
    """真实 chat 调用探测端点可用性（models 200 不代表 chat 可用——key 按模型授权）。"""
    import subprocess

    cmd = [
        "curl", "-s", "--max-time", str(timeout), "-o", "/dev/null", "-w", "%{http_code}",
    ]
    if provider.get("use_proxy") and proxy_url:
        cmd += ["-x", proxy_url]
    cmd += [
        provider["base"].rstrip("/") + "/chat/completions",
        "-H", f"Authorization: Bearer {key}",
        "-H", "Content-Type: application/json",
        "-d", json.dumps({
            "model": provider["model"],
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        return out.stdout.strip() == "200"
    except (OSError, subprocess.TimeoutExpired):
        return False
