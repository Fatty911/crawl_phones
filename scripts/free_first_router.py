#!/usr/bin/env python3
"""Route one request through configured free model endpoints only.

This module deliberately has no paid-provider or subscription credential
knowledge.  A caller may decide to start a separate paid Agent only when the
metadata says that every attempted free endpoint returned HTTP 429.

Every model call is executed through the OpenCode CLI (Agent tool), never by
direct HTTP requests to model APIs.  The OpenCode binary must be installed on
the runner (npm install --global opencode-ai) and its provider configuration
is generated here from the same environment variables the previous direct
calls used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_PROMPT_BYTES = 512 * 1024
MAX_RESPONSE_BYTES = 512 * 1024
MAX_RETRY_AFTER_SECONDS = 5
RETRYABLE_HTTP = {408, 425, 429} | set(range(500, 600))
AUTH_HTTP = {401, 403}


class FreeRouteError(RuntimeError):
    """A bounded failure with a safe classification for the route state machine."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Provider:
    label: str
    key_envs: tuple[str, ...]
    endpoint_env: str
    default_endpoint: str
    model_env: str
    default_models: tuple[str, ...]
    extra_headers: tuple[tuple[str, str], ...] = ()

    def key(self) -> str:
        for name in self.key_envs:
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return ""

    def endpoint(self) -> str:
        value = os.environ.get(self.endpoint_env, "").strip() or self.default_endpoint
        if value.endswith("/chat/completions"):
            return value
        return value.rstrip("/") + "/chat/completions"

    def models(self) -> tuple[str, ...]:
        configured = os.environ.get(self.model_env, "")
        values = tuple(item for item in re.split(r"[,;\s]+", configured.strip()) if item)
        return values or self.default_models


FREE_PROVIDERS = (
    Provider(
        "nvidia-nim",
        ("NVIDIA_NIM_API_KEY",),
        "NVIDIA_NIM_BASE_URL",
        "https://integrate.api.nvidia.com/v1",
        "NVIDIA_NIM_MODEL_LIST",
        (
            "deepseek-ai/deepseek-v4-flash",
            "nvidia/nemotron-3-super-120b-a12b",
            "nvidia/nemotron-3-ultra-550b-a55b",
        ),
    ),
    Provider(
        "openrouter-free",
        ("OPENROUTER_API_KEY",),
        "OPENROUTER_BASE_URL",
        "https://openrouter.ai/api/v1",
        "OPENROUTER_MODEL_LIST",
        ("nvidia/nemotron-3-ultra-550b-a55b:free", "google/gemma-4-31b-it:free"),
        (("HTTP-Referer", "https://github.com/Fatty911"), ("X-Title", "Free-first repair router")),
    ),
    Provider(
        "opencode-zen-free",
        ("ZEN_API_KEY",),
        "ZEN_BASE_URL",
        "https://opencode.ai/zen/v1",
        "ZEN_MODEL_LIST",
        ("nemotron-3-ultra-free", "mimo-v2.5-free"),
    ),
    Provider(
        "cloudflare-workers-ai",
        ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY"),
        "CLOUDFLARE_BASE_URL",
        "https://api.cloudflare.com/client/v4/accounts/b3becce2da2399953658ed2a053e7c08/ai/v1",
        "CLOUDFLARE_MODEL_LIST",
        ("@cf/zai-org/glm-5.2",),
    ),
    Provider(
        "modelscope-free",
        ("MODELSCOPE_API_KEY",),
        "MODELSCOPE_BASE_URL",
        "https://api-inference.modelscope.cn/v1",
        "MODELSCOPE_MODEL_LIST",
        ("MiniMax/MiniMax-M3",),
    ),
    Provider(
        "atomgit-free",
        ("ATOMGIT_API_KEY",),
        "ATOMGIT_BASE_URL",
        "https://api-ai.gitcode.com/v1",
        "ATOMGIT_MODEL_LIST",
        ("zai-org/GLM-5.1",),
    ),
)


def _classify_http(status: int) -> str:
    if status == 429:
        return "rate_limited"
    if status in AUTH_HTTP:
        return "auth_error"
    if 400 <= status < 500:
        return "request_error"
    if status in RETRYABLE_HTTP:
        return "availability_error"
    return "remote_error"


def _retry_after(headers: Any) -> float:
    raw = headers.get("Retry-After", "") if headers is not None else ""
    try:
        return min(MAX_RETRY_AFTER_SECONDS, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return 0.0


def _content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "".join(item.get("text", "") for item in value if isinstance(item, dict)).strip()
    return ""


def _response_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return ""
    return _content(message.get("content"))


def _opencode_base_url(endpoint: str) -> str:
    """OpenCode providers take the API root, not the /chat/completions path."""
    value = endpoint.strip()
    if value.endswith("/chat/completions"):
        return value[: -len("/chat/completions")]
    return value.rstrip("/")


def _build_opencode_config(provider: Provider, model: str, max_tokens: int) -> dict[str, Any]:
    """Build the OPENCODE_CONFIG_CONTENT document for one free provider/model."""
    key_env = next((name for name in provider.key_envs if os.environ.get(name, "").strip()), provider.key_envs[0])
    base_url = _opencode_base_url(provider.endpoint())
    model_limit = {"context": 131072, "output": max(1024, int(max_tokens or 8000))}
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
    config: dict[str, Any] = {
        "provider": {
            provider.label: {
                "npm": "@ai-sdk/openai-compatible",
                "name": provider.label,
                "options": {
                    "baseURL": base_url,
                    "apiKey": f"{{env:{key_env}}}",
                },
                "models": {model: {"limit": model_limit}},
            }
        },
        "agent": {"plan": {"permission": read_only}},
        "permission": read_only,
    }
    return config


def _request(
    provider: Provider,
    model: str,
    prompt: str,
    timeout: float | None = None,
    max_tokens: int | None = None,
) -> tuple[str, int | None, float]:
    """Run one free-provider call through the OpenCode CLI (Agent tool).

    The CLI is invoked with an isolated config so the model key is consumed
    only by the Agent tool process, never by this script.  A nonzero exit or
    an empty response is treated as a failed attempt, mirroring the previous
    direct-HTTP state machine.
    """
    if not provider.key():
        return "", None, 0.0
    effective_tokens = max_tokens if max_tokens is not None else int(os.environ.get("FREE_LLM_MAX_TOKENS", "8000"))
    request_timeout = timeout if timeout is not None else float(os.environ.get("FREE_LLM_TIMEOUT", "180"))
    opencode_bin = os.environ.get("OPENCODE_BIN", "opencode")
    config = _build_opencode_config(provider, model, effective_tokens)
    instruction = (
        "Answer the attached prompt directly. Do not call any tools and do not "
        "modify any files. Return only the requested analysis."
    )
    env = dict(os.environ)
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config, ensure_ascii=False)
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    env["OPENCODE_DISABLE_TELEMETRY"] = "1"
    with tempfile.TemporaryDirectory(prefix="free-router-") as tmpdir:
        prompt_path = Path(tmpdir) / "prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        cmd = [
            opencode_bin, "run", "--pure", "--agent", "plan",
            "--model", f"{provider.label}/{model}",
            "--format", "default",
            "--dir", tmpdir,
            "--file", "prompt.md",
            instruction,
        ]
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max(240.0, request_timeout + 60.0),
                env=env,
            )
        except FileNotFoundError:
            raise FreeRouteError("availability_error", "opencode CLI is not installed") from None
        except subprocess.TimeoutExpired:
            raise FreeRouteError("availability_error", "opencode call timed out") from None
        if completed.returncode != 0:
            combined = (completed.stderr or "") + (completed.stdout or "")
            if re.search(r"\b429\b|rate.?limit|quota", combined, re.I):
                return "", 429, 0.0
            if re.search(r"\b401\b|\b403\b|unauthorized|invalid api key|auth", combined, re.I):
                return "", 401, 0.0
            return "", None, 0.0
        text = (completed.stdout or "").strip()
        if not text:
            raise FreeRouteError("protocol_error", "opencode returned no visible message content")
        return text, 200, 0.0


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_./:-]", "_", value)[:160]


def _write_outputs(metadata: dict[str, Any], path: Path | None, github_output: Path | None) -> None:
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if github_output:
        github_output.parent.mkdir(parents=True, exist_ok=True)
        fields = {
            "free_status": str(metadata["status"]),
            "paid_required": "true" if metadata["paid_required"] else "false",
            "free_attempted": str(metadata["attempted"]),
            "free_provider": _safe(str(metadata.get("provider") or "")),
            "free_model": _safe(str(metadata.get("model") or "")),
        }
        with github_output.open("a", encoding="utf-8") as handle:
            for key, value in fields.items():
                handle.write(f"{key}={value}\n")


def route(
    prompt: str,
    output: Path,
    metadata_output: Path | None,
    github_output: Path | None,
    providers: tuple[Provider, ...] | None = None,
    timeout: float | None = None,
    max_tokens: int | None = None,
) -> int:
    provider_list = providers or FREE_PROVIDERS
    attempts: list[dict[str, Any]] = []
    configured = 0
    configured_total = sum(1 for provider in provider_list if provider.key())
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    request_id = prompt_sha256[:16]
    for provider in provider_list:
        key = provider.key()
        if not key:
            continue
        configured += 1
        for model in provider.models():
            record: dict[str, Any] = {"provider": provider.label, "model": model}
            try:
                text, status, retry_after = _request(
                    provider,
                    model,
                    prompt,
                    timeout=timeout,
                    max_tokens=max_tokens,
                )
                if text:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text(text, encoding="utf-8")
                    metadata = {
                        "version": 1,
                        "request_id": request_id,
                        "prompt_sha256": prompt_sha256,
                        "status": "success",
                        "paid_required": False,
                        "attempted": len(attempts) + 1,
                        "configured_providers": configured_total,
                        "provider": provider.label,
                        "model": model,
                        "attempts": attempts + [dict(record, status=status or 200, kind="success")],
                    }
                    _write_outputs(metadata, metadata_output, github_output)
                    return 0
                record.update(
                    status=status if status is not None else 200,
                    kind=_classify_http(status) if status is not None else "protocol_error",
                )
                if retry_after:
                    time.sleep(retry_after)
            except FreeRouteError as exc:
                record.update(status=None, kind=exc.kind, error=str(exc))
            except RuntimeError as exc:
                record.update(status=None, kind="availability_error", error=type(exc).__name__)
            attempts.append(record)

    statuses = [item.get("kind") for item in attempts]
    if attempts and all(kind == "rate_limited" for kind in statuses):
        status = "all_free_429"
        paid_required = True
    elif not configured:
        status = "no_credentials"
        paid_required = False
    elif any(kind == "auth_error" for kind in statuses):
        status = "auth_error"
        paid_required = False
    elif any(kind == "request_error" for kind in statuses):
        status = "request_error"
        paid_required = False
    elif attempts:
        status = "free_unavailable"
        paid_required = False
    else:
        status = "no_credentials"
        paid_required = False
    metadata = {
        "version": 1,
        "request_id": request_id,
        "prompt_sha256": prompt_sha256,
        "status": status,
        "paid_required": paid_required,
        "attempted": len(attempts),
        "configured_providers": configured_total,
        "provider": "",
        "model": "",
        "attempts": attempts,
    }
    _write_outputs(metadata, metadata_output, github_output)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--metadata-output", required=True)
    parser.add_argument("--github-output")
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--max-tokens", type=int)
    args = parser.parse_args()
    prompt_path = Path(args.prompt_file)
    raw = prompt_path.read_bytes()
    if not raw or len(raw) > MAX_PROMPT_BYTES:
        raise SystemExit("prompt is empty or exceeds the size limit")
    try:
        prompt = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit("prompt is not UTF-8") from exc
    output = Path(args.output)
    if output.exists():
        output.unlink()
    return route(
        prompt,
        output,
        Path(args.metadata_output),
        Path(args.github_output) if args.github_output else None,
        timeout=args.timeout,
        max_tokens=args.max_tokens,
    )


if __name__ == "__main__":
    raise SystemExit(main())
