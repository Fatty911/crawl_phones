#!/usr/bin/env python3
"""Create or update cron-job.org jobs for repository_dispatch crawler triggers."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import requests


ENDPOINT = "https://api.cron-job.org"
DEFAULT_JOBS = {
    "morning": (8, 30),
    "afternoon": (13, 30),
}


def headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def request_json(
    method: str,
    path: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
    attempts: int = 4,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.request(
                method,
                ENDPOINT + path,
                headers=headers(api_key),
                data=json.dumps(payload) if payload is not None else None,
                timeout=30,
            )
            break
        except requests.RequestException as exc:
            last_error = exc
            if attempt == attempts:
                raise RuntimeError(f"{method} {path} failed after {attempts} attempts: {exc}") from exc
            wait_seconds = min(30, attempt * 5)
            print(f"{method} {path} attempt {attempt}/{attempts} failed; retrying in {wait_seconds}s")
            time.sleep(wait_seconds)
    else:
        raise RuntimeError(f"{method} {path} failed: {last_error}")

    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} failed: HTTP {response.status_code} {response.text[:500]}")
    if not response.text.strip():
        return {}
    return response.json()


def build_job(repo: str, profile: str, hour: int, minute: int, github_token: str) -> dict[str, Any]:
    body = {
        "event_type": "trigger-crawl",
        "client_payload": {
            "source": "cron-job-org",
            "profile": profile,
            "crawler": "all",
        },
    }
    return {
        "title": f"{repo} crawl trigger {profile}",
        "enabled": True,
        "saveResponses": True,
        "url": f"https://api.github.com/repos/{repo}/dispatches",
        "requestMethod": 1,
        "requestTimeout": 30,
        "schedule": {
            "timezone": "Asia/Shanghai",
            "expiresAt": 0,
            "hours": [hour],
            "mdays": [-1],
            "minutes": [minute],
            "months": [-1],
            "wdays": [-1],
        },
        "extendedData": {
            "headers": {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {github_token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            "body": json.dumps(body, separators=(",", ":")),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "Fatty911/crawl_phones"))
    parser.add_argument("--cron-api-key-env", default="CRON_JOB_ORG_API_KEY")
    parser.add_argument("--github-token-env", default="GITHUB_DISPATCH_TOKEN")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cron_api_key = os.environ.get(args.cron_api_key_env)
    github_token = os.environ.get(args.github_token_env)
    if args.dry_run:
        cron_api_key = cron_api_key or "dry-run-cron-token"
        github_token = github_token or "dry-run-github-token"
    elif not cron_api_key:
        raise SystemExit(f"Missing {args.cron_api_key_env}; cannot call cron-job.org API.")
    if not github_token:
        raise SystemExit(f"Missing {args.github_token_env}; cannot configure GitHub dispatch headers.")

    existing = [] if args.dry_run else request_json("GET", "/jobs", cron_api_key).get("jobs", [])
    by_title = {job.get("title"): job for job in existing}

    for profile, (hour, minute) in DEFAULT_JOBS.items():
        job = build_job(args.repo, profile, hour, minute, github_token)
        title = job["title"]
        payload = {"job": job}
        if args.dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            continue
        if title in by_title:
            job_id = by_title[title]["jobId"]
            request_json("PATCH", f"/jobs/{job_id}", cron_api_key, payload)
            print(f"Updated {title} (jobId={job_id})")
        else:
            result = request_json("PUT", "/jobs", cron_api_key, payload)
            print(f"Created {title} (jobId={result.get('jobId')})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
