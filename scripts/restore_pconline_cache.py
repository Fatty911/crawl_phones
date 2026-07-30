#!/usr/bin/env python3
"""Restore the newest usable PConline raw cache from GitHub Actions artifacts."""

import argparse
import io
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


ARTIFACT_PREFIX = "pconline-phone-data-early-"
GITHUB_API = "https://api.github.com"
MAX_HTTP_RESPONSE_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 2_000
MAX_MEMBER_BYTES = 2 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
VALIDATION_FIELDS = (
    "上市时间",
    "处理器",
    "内存",
    "存储",
    "屏幕",
    "电池",
    "摄像头参数",
)
MISSING_VALUES = {"", "-", "--", "/", "n/a", "null", "暂无", "无", "未知"}


class InvalidCacheArtifact(ValueError):
    """An artifact is structurally or semantically unsafe to restore."""


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not leak GitHub credentials to the signed artifact storage host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and urlsplit(req.full_url).netloc != urlsplit(newurl).netloc:
            redirected.remove_header("Authorization")
        return redirected


def _valid_candidates(artifacts, branch, exclude_run_id=None):
    candidates = []
    for artifact in artifacts:
        workflow_run = artifact.get("workflow_run") or {}
        if not str(artifact.get("name", "")).startswith(ARTIFACT_PREFIX):
            continue
        if artifact.get("expired"):
            continue
        if branch and workflow_run.get("head_branch") != branch:
            continue
        if exclude_run_id is not None and str(workflow_run.get("id")) == str(
            exclude_run_id
        ):
            continue
        candidates.append(artifact)
    return sorted(
        candidates, key=lambda item: item.get("created_at", ""), reverse=True
    )


def is_semantically_valid_record(payload, expected_id):
    if not isinstance(payload, dict):
        return False
    phone_id = str(payload.get("phone_id") or payload.get("id") or "")
    model_name = str(payload.get("型号") or payload.get("name") or "").strip()
    brand = str(payload.get("品牌") or "").strip()
    source = str(payload.get("source") or "").strip()
    raw_url = str(payload.get("url") or "").strip()
    release_text = " ".join(
        str(payload.get(field) or "")
        for field in ("上市时间", "发布时间", "发布日期", "上市日期")
    )
    release_match = re.search(r"(\d{4})", release_text)
    valid_specs = sum(
        str(payload.get(field) or "").strip().lower() not in MISSING_VALUES
        for field in VALIDATION_FIELDS
    )
    return bool(
        phone_id == str(expected_id)
        and model_name
        and brand
        and source == "太平洋电脑网"
        and urlsplit(raw_url).hostname == "product.pconline.com.cn"
        and release_match
        and 2021 <= int(release_match.group(1)) <= 2030
        and valid_specs >= 4
    )


def _read_raw_files(archive_bytes):
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise InvalidCacheArtifact("raw-cache archive exceeds compressed size limit")
    raw_files = {}
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as bundle:
            members = bundle.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise InvalidCacheArtifact("raw-cache archive has too many members")
            if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
                raise InvalidCacheArtifact("raw-cache archive exceeds expanded size limit")
            for member in members:
                if member.file_size > MAX_MEMBER_BYTES:
                    raise InvalidCacheArtifact(
                        f"raw-cache member exceeds size limit: {member.filename}"
                    )
                normalized_name = member.filename.replace("\\", "/")
                path = PurePosixPath(normalized_name)
                if path.is_absolute() or ".." in path.parts:
                    raise InvalidCacheArtifact(
                        f"unsafe raw-cache path: {member.filename}"
                    )
                if member.is_dir():
                    continue
                if not path.parts or path.parts[0] != "json":
                    continue
                if (
                    len(path.parts) != 2
                    or path.suffix != ".json"
                    or not path.stem.isdigit()
                ):
                    raise InvalidCacheArtifact(
                        f"invalid raw-cache path: {member.filename}"
                    )
                data = bundle.read(member)
                payload = json.loads(data.decode("utf-8"))
                if not is_semantically_valid_record(payload, path.stem):
                    raise InvalidCacheArtifact(
                        f"raw-cache record is not publishable: {member.filename}"
                    )
                if path.name in raw_files:
                    raise InvalidCacheArtifact(
                        f"duplicate raw-cache entry: {member.filename}"
                    )
                raw_files[path.name] = data
    except InvalidCacheArtifact:
        raise
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as exc:
        raise InvalidCacheArtifact("raw-cache archive cannot be parsed") from exc
    if not raw_files:
        raise InvalidCacheArtifact("artifact contains no raw phone cache")
    return raw_files


def _replace_destination(raw_files, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.restore-", dir=destination.parent)
    )
    backup = destination.parent / f".{destination.name}.backup-{uuid.uuid4().hex}"
    moved_existing = False
    try:
        for name, data in raw_files.items():
            (staging / name).write_bytes(data)
        if destination.exists():
            destination.replace(backup)
            moved_existing = True
        try:
            staging.replace(destination)
        except Exception:
            if moved_existing and backup.exists() and not destination.exists():
                backup.replace(destination)
            raise
        if moved_existing:
            shutil.rmtree(backup)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup.exists() and destination.exists():
            shutil.rmtree(backup)


def restore_latest_cache(
    artifacts,
    download_archive,
    destination,
    *,
    branch="main",
    exclude_run_id=None,
):
    """Restore the newest semantically valid raw cache, without restoring progress."""
    destination = Path(destination)
    for candidate in _valid_candidates(artifacts, branch, exclude_run_id):
        try:
            raw_files = _read_raw_files(download_archive(candidate))
        except InvalidCacheArtifact:
            continue

        _replace_destination(raw_files, destination)
        return {
            "artifact_id": candidate["id"],
            "workflow_run_id": (candidate.get("workflow_run") or {}).get("id"),
            "raw_count": len(raw_files),
        }
    return None


def _github_request(url, token, *, accept="application/vnd.github+json"):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "crawl-phones-pconline-cache-restore",
        },
    )
    opener = urllib.request.build_opener(SafeRedirectHandler())
    with opener.open(request, timeout=60) as response:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_HTTP_RESPONSE_BYTES:
            raise OSError("GitHub response exceeds size limit")
        data = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
        if len(data) > MAX_HTTP_RESPONSE_BYTES:
            raise OSError("GitHub response exceeds size limit")
        return data


def list_repository_artifacts(repository, token):
    artifacts = []
    page = 1
    while True:
        payload = json.loads(
            _github_request(
                f"{GITHUB_API}/repos/{repository}/actions/artifacts"
                f"?per_page=100&page={page}",
                token,
            )
        )
        batch = payload.get("artifacts", [])
        if not isinstance(batch, list):
            raise ValueError("GitHub artifact response has no artifact list")
        artifacts.extend(batch)
        if len(batch) < 100:
            return artifacts
        page += 1


def restore_repository_cache(repository, token, destination, branch, exclude_run_id):
    artifacts = list_repository_artifacts(repository, token)

    def download(candidate):
        url = candidate.get("archive_download_url")
        if not url:
            url = (
                f"{GITHUB_API}/repos/{repository}/actions/artifacts/"
                f"{candidate['id']}/zip"
            )
        return _github_request(url, token, accept="application/vnd.github+json")

    return restore_latest_cache(
        artifacts,
        download,
        destination,
        branch=branch,
        exclude_run_id=exclude_run_id,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--token", default=os.getenv("GH_TOKEN"), required=False)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--exclude-run-id")
    args = parser.parse_args()

    if not args.token:
        parser.error("--token or GH_TOKEN is required")

    result = restore_repository_cache(
        args.repo,
        args.token,
        args.destination,
        args.branch,
        args.exclude_run_id,
    )
    if result:
        print(
            "Restored "
            f"{result['raw_count']} raw PConline records from artifact "
            f"{result['artifact_id']} (run {result['workflow_run_id']})."
        )
    else:
        print("No semantically valid PConline raw-cache artifact is available.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
