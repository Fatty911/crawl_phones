#!/usr/bin/env python3
"""扫描仓库中仍在直连使用模型 API key 的代码。

规则：GitHub Actions 工作流路径（.github/、scripts/、custom_scripts/ 等）中
调用 AI 大模型必须通过 Agent 工具（OpenCode/Codex/Hermes/MiMo/Kilo 等 CLI），
禁止脚本直接向模型 API 发 HTTP 请求。

检测为文件级分析：key 定义、认证头、HTTP 调用、LLM 端点可能分布在多行。

排除项（合法）：
- Agent 工具子进程调用（opencode/codex/hermes/kilo 命令）
- GitHub API / gh CLI（GH_TOKEN 等，无 LLM 端点）
- 公开端点模型列表抓取（/models 不带 key）
- 应用本体功能（LibreChat api/、packages/ 等产品代码，非工作流路径）

用法：
    python3 scripts/scan_direct_llm_calls.py [路径...]
    无参数时扫描仓库根；返回码 1 表示发现违规。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# 模型 API 端点特征（URL 或路径中出现即视为 LLM 调用）
LLM_URL_RE = re.compile(
    r"https?://[^\"'\s`]*?(?:openai\.com|api\.anthropic\.com|api\.deepseek\.com|"
    r"api\.moonshot\.cn|api\.kimi\.com|openrouter\.ai|zenmux\.ai|opencode\.ai/zen|"
    r"ark\.cn-beijing|dashscope|api\.scnet\.cn|integrate\.api\.nvidia\.com|"
    r"generativelanguage|googleapis\.com/v1beta|api\.mistral\.ai|api\.groq\.com|"
    r"x\.ai|grok\.ai|api\.minimax\.io|api\.z\.ai|api\.githubcopilot\.com|"
    r"claude\.ai|api\.baidu\.com|qianfan|volces\.com|maas\.volces|"
    r"api-inference\.modelscope\.cn|api-ai\.gitcode\.com|api\.cloudflare\.com/client/v4/accounts/[^/]+/ai)",
    re.I,
)
LLM_PATH_RE = re.compile(
    r"/chat/completions|/v1/messages|generateContent|/completions\b", re.I
)
# 认证头（HTTP 头上下文；环境变量名 XXX_API_KEY 不在此列）
AUTH_RE = re.compile(
    r"Authorization|Bearer|x-api-key|X-Api-Key|[\"']apiKey[\"']\s*[:=]", re.I
)
# HTTP 调用
HTTP_CALL_RE = re.compile(
    r"requests\.(get|post|put|delete|patch)|urllib\.request|urlopen\(|"
    r"fetch\(|axios|curl |Invoke-RestMethod|wget ", re.I
)
# 模型 API key 环境变量
KEY_ENV_RE = re.compile(
    r"(OPENAI_API_KEY|ANTHROPIC_API_KEY|DEEPSEEK_API_KEY|MOONSHOT_API_KEY|"
    r"KIMI[_-]?API[_-]?KEY|ZENMUX[_-]?API[_-]?KEY|ZEN[_-]?API[_-]?KEY|"
    r"NIM[_-]?API[_-]?KEY|NVIDIA[_-]?API[_-]?KEY|ARK[_-]?API[_-]?KEY|"
    r"DASHSCOPE[_-]?API[_-]?KEY|SCNET[_-]?API[_-]?KEY|GROK[_-]?API[_-]?KEY|"
    r"QINIU[_-]?API[_-]?KEY|MOONSCOPE[_-]?API[_-]?KEY|GEMINI[_-]?API[_-]?KEY|"
    r"MISTRAL[_-]?API[_-]?KEY|OPENROUTER[_-]?API[_-]?KEY|VOLCENGINE[_-]?.*API[_-]?KEY|"
    r"ALIBABA[_-]?.*API[_-]?KEY|OPENCODE[_-]?.*API[_-]?KEY|BAILIAN[_-]?API[_-]?KEY|"
    r"QIANFAN[_-]?API[_-]?KEY|ZHIPU[_-]?API[_-]?KEY|SILICONFLOW[_-]?API[_-]?KEY|"
    r"MODELSCOPE[_-]?API[_-]?KEY|ATOMGIT[_-]?API[_-]?KEY|MODAL[_-]?API[_-]?KEY|"
    r"CLOUDFLARE[_-]?API[_-]?KEY|MINIMAX[_-]?API[_-]?KEY|XAI[_-]?API[_-]?KEY|"
    r"OLLAMA[_-]?API[_-]?KEY|MIMO[_-]?API[_-]?KEY|UNICOM[_-]?.*API[_-]?KEY|"
    r"TENCENT[_-]?.*API[_-]?KEY|BLTCY[_-]?API[_-]?KEY|DALLE[_-]?API[_-]?KEY|"
    r"FLUX[_-]?API[_-]?KEY|IMAGE_GEN[_-]?.*KEY)", re.I
)
# Agent 工具子进程调用（合法消费 key 的途径）
AGENT_CALL_RE = re.compile(
    r"\b(opencode|codex|hermes(?:-agent)?|mimo|kilocode|kilo-code|kilo|omo|"
    r"claude(?:-code)?)\b.*\b(run|exec|chat)\b", re.I
)
AGENT_NAME_RE = re.compile(r"\b(opencode|codex|hermes|kilo|claude)\b", re.I)

# 跳过目录（应用本体/依赖/构建产物）
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", "dist", "build", ".next",
    "docs", "public", "api", "packages", "client", "server",
    "venv", ".venv", "site", "data", "crawl_state",
}
# 允许的公开 /models 列表抓取
PUBLIC_MODELS_FETCH_RE = re.compile(
    r"fetch\(['\"][^'\"]*/models['\"]|https?://[^ '\"]*/models", re.I
)


def _line_is_config_or_public(line: str) -> bool:
    """排除合法行：opencode 配置注入、git 认证、baseURL 配置、公开 /models 抓取、
    workflow env 注入（secrets → 环境变量，由 Agent 工具消费）。"""
    if "OPENCODE_CONFIG" in line:
        return True
    if '"npm":"@ai-sdk/' in line or "'npm':'@ai-sdk/" in line:
        return True  # opencode/agent provider 配置（key 由 Agent 工具消费）
    if "extraheader" in line.lower():
        return True  # git push 认证（GitHub，非模型 API）
    if "secrets." in line and ":" in line:
        return True  # workflow env 注入行
    if ("baseURL" in line or "base_url" in line or "endpoint" in line) and not HTTP_CALL_RE.search(line):
        return True  # provider 端点配置数据
    if "https://" in line and not HTTP_CALL_RE.search(line) and not AUTH_RE.search(line):
        return True  # URL 常量/配置赋值（无 HTTP 调用同行）
    if "/chat/completions" in line and not HTTP_CALL_RE.search(line):
        return True  # baseURL 字符串处理（endswith/rstrip/拼接），无实际请求
    if PUBLIC_MODELS_FETCH_RE.search(line) and not AUTH_RE.search(line):
        return True  # 公开模型列表抓取
    if 'apiKey' in line and not HTTP_CALL_RE.search(line):
        return True  # key 赋值/配置（无 HTTP 调用同行）
    return False


def scan_file(path: Path) -> list[tuple[int, str]]:
    """文件级分析：key 定义、认证头、HTTP 调用、LLM 端点可能分布在多行。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    has_key = False
    has_http = False
    has_llm = False
    has_agent = False
    auth_lines: set[int] = set()
    for i, line in enumerate(lines, 1):
        if AUTH_RE.search(line) or KEY_ENV_RE.search(line):
            has_key = True
            if AUTH_RE.search(line):
                auth_lines.add(i)
        if HTTP_CALL_RE.search(line):
            has_http = True
        if LLM_URL_RE.search(line) or LLM_PATH_RE.search(line):
            has_llm = True
        if AGENT_CALL_RE.search(line) or AGENT_NAME_RE.search(line):
            has_agent = True
    if not (has_key and has_http and has_llm):
        return []

    # 列出嫌疑行并过滤配置/公开抓取
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(lines, 1):
        if (i in auth_lines or LLM_URL_RE.search(line) or LLM_PATH_RE.search(line)) \
                and not _line_is_config_or_public(line):
            hits.append((i, line.strip()[:220]))
    if not hits:
        return []
    if has_agent:
        hits.insert(0, (0, "[文件含 Agent 工具调用，但仍检出 key/认证与模型端点同文件——请人工确认直连点]"))
    return hits


def scan_root(root: Path) -> list[tuple[Path, list[tuple[int, str]]]]:
    findings: list[tuple[Path, list[tuple[int, str]]]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            if not fname.endswith((".py", ".js", ".ts", ".sh", ".yml", ".yaml")):
                continue
            path = Path(dirpath) / fname
            hits = scan_file(path)
            if hits:
                findings.append((path.relative_to(root), hits))
    return findings


def main() -> int:
    roots = [Path(p) for p in sys.argv[1:]] or [Path(".")]
    total = 0
    for root in roots:
        if root.is_file():
            hits = scan_file(root)
            if hits:
                for lineno, line in hits:
                    total += 1
                    prefix = f"{root}:{lineno}" if lineno else f"{root}:FILE"
                    print(f"{prefix}: {line}")
            continue
        for rel, hits in scan_root(root):
            for lineno, line in hits:
                total += 1
                prefix = f"{rel}:{lineno}" if lineno else f"{rel}:FILE"
                print(f"{prefix}: {line}")
    if total:
        print(f"\n[FAIL] 发现疑似模型 API key 直连（必须改为通过 Agent 工具调用）")
        return 1
    print("[PASS] 未发现模型 API key 直连")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
