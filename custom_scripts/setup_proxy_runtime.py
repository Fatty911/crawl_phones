#!/usr/bin/env python3
"""Prepare a mihomo proxy runtime for GitHub Actions crawlers."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from generate_clash_config import ClashConfigGenerator, redact_url


MIHOMO_API = "https://api.github.com/repos/MetaCubeX/mihomo/releases/latest"
DEFAULT_TEST_URLS = [
    "https://www.bing.com",
    "https://www.baidu.com",
    "https://www.pconline.com.cn",
]


def append_github_env(path: str, values: dict[str, str]) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        for key, value in values.items():
            f.write(f"{key}={value}\n")


def mask(value: str) -> None:
    if value:
        print(f"::add-mask::{value}")


def split_plain_urls(raw: str) -> list[str]:
    parts = re.split(r"[\r\n;|,]+", raw)
    return [part.strip() for part in parts if part.strip()]


def parse_proxy_secret(raw: str) -> tuple[list[str], list[str]]:
    raw = (raw or "").strip()
    if not raw or raw.lower() == "null":
        return [], []

    subscriptions: list[str] = []
    exclude_keywords: list[str] = []

    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        subscriptions = split_plain_urls(raw)
    else:
        if isinstance(data, dict):
            raw_subs = data.get("subscriptions") or data.get("subs") or []
            raw_exclude = data.get("exclude_keywords") or data.get("exclude") or []
            if isinstance(raw_subs, str):
                subscriptions = split_plain_urls(raw_subs)
            elif isinstance(raw_subs, list):
                subscriptions = [str(item).strip() for item in raw_subs if str(item).strip()]
            if isinstance(raw_exclude, str):
                exclude_keywords = [item.strip() for item in re.split(r"[\r\n,;|]+", raw_exclude) if item.strip()]
            elif isinstance(raw_exclude, list):
                exclude_keywords = [str(item).strip() for item in raw_exclude if str(item).strip()]
        elif isinstance(data, list):
            subscriptions = [str(item).strip() for item in data if str(item).strip()]
        elif isinstance(data, str):
            subscriptions = split_plain_urls(data)

    deduped: list[str] = []
    seen: set[str] = set()
    for url in subscriptions:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            print(f"跳过无效订阅地址: {url[:20]}***")
            continue
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
        mask(url)

    return deduped, exclude_keywords


def find_mihomo(bin_dir: Path) -> Path | None:
    existing = shutil.which("mihomo")
    if existing:
        return Path(existing)
    candidate = bin_dir / "mihomo"
    return candidate if candidate.exists() else None


def choose_mihomo_asset(release: dict[str, Any]) -> str | None:
    assets = release.get("assets", [])
    candidates = []
    for asset in assets:
        name = str(asset.get("name", "")).lower()
        url = asset.get("browser_download_url")
        if not url:
            continue
        if "linux" not in name or "amd64" not in name:
            continue
        if not name.endswith(".gz"):
            continue
        if any(token in name for token in ["deb", "rpm", "pkg", "debug"]):
            continue
        score = 0
        if "compatible" in name:
            score += 10
        if "go120" in name or "go121" in name:
            score -= 1
        candidates.append((score, name, str(url)))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][2]


def download_mihomo(bin_dir: Path) -> Path | None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / "mihomo"

    try:
        print("下载 mihomo 最新 Linux amd64 运行文件...")
        req = urllib.request.Request(MIHOMO_API, headers={"User-Agent": "crawl-cars-actions"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            release = json.loads(resp.read().decode("utf-8"))
        asset_url = choose_mihomo_asset(release)
        if not asset_url:
            print("未找到可用的 mihomo linux-amd64 gz 资产")
            return None

        req = urllib.request.Request(asset_url, headers={"User-Agent": "crawl-cars-actions"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            compressed = resp.read()
        binary = gzip.decompress(compressed)
        target.write_bytes(binary)
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"mihomo 已准备: {target}")
        return target
    except Exception as exc:
        print(f"下载 mihomo 失败: {exc}")
        return None


def parse_nodes(subscriptions: list[str], exclude_keywords: list[str]) -> list[dict[str, Any]]:
    generator = ClashConfigGenerator()
    proxies: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url in subscriptions:
        print(f"解析订阅: {redact_url(url)}")
        for proxy in generator.parse_subscription(url, exclude_keywords):
            name = str(proxy.get("name") or "")
            key = name or json.dumps(proxy, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            proxies.append(proxy)
    return proxies


def write_runtime_files(proxy_config: Path, clash_config: Path,
                        subscriptions: list[str], exclude_keywords: list[str],
                        proxies: list[dict[str, Any]]) -> None:
    proxy_config.parent.mkdir(parents=True, exist_ok=True)
    proxy_config.write_text(
        json.dumps(
            {
                "subscriptions": subscriptions,
                "exclude_keywords": exclude_keywords,
                "node_count": len(proxies),
                "proxies": [],
                "stats": {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    generator = ClashConfigGenerator(str(clash_config))
    config = generator.generate_config_from_proxies(proxies)
    generator.save_config(config, str(clash_config))


def wait_for_controller(timeout: int = 15) -> bool:
    session = requests.Session()
    session.trust_env = False
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = session.get("http://127.0.0.1:9090/version", timeout=2)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            time.sleep(1)
    return False


def test_local_proxy(urls: list[str], max_retries: int = 3, retry_delay: int = 5) -> bool:
    """Test local mihomo proxy connectivity with retries.

    mihomo load-balance group needs time to establish tunnels to remote nodes
    after startup. A single immediate test often fails with SSLEOFError because
    the proxy tunnel is not yet ready. Retry each URL up to max_retries times.
    """
    local_proxy = {
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    }
    session = requests.Session()
    session.trust_env = False
    for attempt in range(1, max_retries + 1):
        for url in urls:
            try:
                resp = session.get(url, proxies=local_proxy, timeout=15)
                if 200 <= resp.status_code < 400:
                    print(f"代理连通性测试通过: {url} HTTP {resp.status_code} (第{attempt}次尝试)")
                    return True
                print(f"代理连通性测试未通过: {url} HTTP {resp.status_code} (第{attempt}次尝试)")
            except requests.RequestException as exc:
                print(f"代理连通性测试异常: {url} (第{attempt}次尝试) {exc}")
        if attempt < max_retries:
            print(f"等待 {retry_delay} 秒后重试 (剩余 {max_retries - attempt} 次)...")
            time.sleep(retry_delay)
    return False


def disable_proxy(github_env: str, reason: str) -> int:
    print(f"{reason}，将无代理直连")
    append_github_env(
        github_env,
        {
            "PROXY_ENABLED": "false",
            "PROXY_CONFIG_FILE": "",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "ALL_PROXY": "",
            "http_proxy": "",
            "https_proxy": "",
            "all_proxy": "",
        },
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Setup mihomo proxy runtime")
    parser.add_argument("--github-env", default=os.getenv("GITHUB_ENV", ""))
    parser.add_argument("--proxy-config", default="/tmp/proxies.json")
    parser.add_argument("--clash-config", default="/tmp/mihomo/config.yaml")
    parser.add_argument("--bin-dir", default="/tmp/mihomo-bin")
    parser.add_argument("--test-url", action="append", default=[])
    args = parser.parse_args()

    raw = os.getenv("PROXY_SUBSCRIPTIONS", "")
    subscriptions, exclude_keywords = parse_proxy_secret(raw)
    if not subscriptions:
        return disable_proxy(args.github_env, "未配置 PROXY_SUBSCRIPTIONS 或没有有效订阅地址")

    proxies = parse_nodes(subscriptions, exclude_keywords)
    if not proxies:
        return disable_proxy(args.github_env, "订阅已获取但没有解析到可用节点")

    print(f"解析到 {len(proxies)} 个代理节点，准备启动本地 mihomo")
    proxy_config = Path(args.proxy_config)
    clash_config = Path(args.clash_config)
    write_runtime_files(proxy_config, clash_config, subscriptions, exclude_keywords, proxies)

    mihomo = find_mihomo(Path(args.bin_dir)) or download_mihomo(Path(args.bin_dir))
    if not mihomo:
        return disable_proxy(args.github_env, "mihomo 不可用")

    log_path = Path("/tmp/mihomo.log")
    log_file = log_path.open("ab")
    process = subprocess.Popen(
        [str(mihomo), "-d", str(clash_config.parent), "-f", str(clash_config)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"mihomo PID: {process.pid}, 日志: {log_path}")

    if not wait_for_controller():
        process.terminate()
        return disable_proxy(args.github_env, "mihomo 控制端口未就绪")

    test_urls = args.test_url or DEFAULT_TEST_URLS
    if not test_local_proxy(test_urls):
        process.terminate()
        return disable_proxy(args.github_env, "所有代理节点连通性测试失败")

    append_github_env(
        args.github_env,
        {
            "PROXY_ENABLED": "true",
            "PROXY_CONFIG_FILE": str(proxy_config),
            "HTTP_PROXY": "http://127.0.0.1:7890",
            "HTTPS_PROXY": "http://127.0.0.1:7890",
            "ALL_PROXY": "socks5://127.0.0.1:7891",
            "http_proxy": "http://127.0.0.1:7890",
            "https_proxy": "http://127.0.0.1:7890",
            "all_proxy": "socks5://127.0.0.1:7891",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        },
    )
    print("代理已启用：后续爬虫步骤将通过 http://127.0.0.1:7890 访问外网")
    return 0


if __name__ == "__main__":
    sys.exit(main())
