#!/usr/bin/env python3
"""Route one request through configured free model endpoints only.

This module deliberately has no paid-provider or subscription credential
knowledge.  A caller may decide to start a separate paid Agent only when the
metadata says that every attempted free endpoint returned HTTP 429.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
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
        ("@cf/zai-org/glm-5.2", "@cf/moonshotai/kimi-k2.6"),
    ),
    Provider(
        "modal-free",
        ("MODAL_API_KEY",),
        "MODAL_BASE_URL",
        "https://api.us-west-2.modal.direct/v1",
        "MODAL_MODEL_LIST",
        ("zai-org/GLM-5.1-FP8",),
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


def _request(
    provider: Provider,
    model: str,
    prompt: str,
    timeout: float | None = None,
    max_tokens: int | None = None,
) -> tuple[str, int | None, float]:
    try:
        request_payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": float(os.environ.get("FREE_LLM_TEMPERATURE", "0.1")),
            "max_tokens": max_tokens if max_tokens is not None else int(os.environ.get("FREE_LLM_MAX_TOKENS", "8000")),
        }
        if os.environ.get("FREE_LLM_JSON_MODE", "").strip().lower() in {"1", "true", "yes"}:
            request_payload["response_format"] = {"type": "json_object"}
        payload = json.dumps(
            request_payload,
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Authorization": f"Bearer {provider.key()}", "Content-Type": "application/json"}
        headers.update(dict(provider.extra_headers))
        request = urllib.request.Request(provider.endpoint(), data=payload, headers=headers, method="POST")
        request_timeout = timeout if timeout is not None else float(os.environ.get("FREE_LLM_TIMEOUT", "120"))
        with urllib.request.urlopen(request, timeout=request_timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("response exceeds size limit")
            value = _response_text(json.loads(raw.decode("utf-8")))
            if not value:
                raise ValueError("response has no visible message content")
            return value, response.status, 0.0
    except urllib.error.HTTPError as exc:
        return "", exc.code, _retry_after(exc.headers)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FreeRouteError("availability_error", type(exc).__name__) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise FreeRouteError("protocol_error", type(exc).__name__) from exc


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
