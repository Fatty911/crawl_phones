#!/usr/bin/env python3
"""Review-only snapshot regression gate; no network, dependencies or repo execution.

This is a deliberately bounded detector, NOT proof of no secrets or a history scan.
All stdout/stderr diagnostics omit source bytes and raw file names.
"""
from __future__ import annotations

import argparse
from array import array
from bisect import bisect_left
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from collections import Counter
from dataclasses import dataclass
from collections.abc import Iterator


MARKDOWN = {".md", ".markdown", ".mdown", ".mkd", ".mdx"}
REPORT_VERSION = 2
ASCII_ALNUM = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
EMAIL_LOCAL = ASCII_ALNUM | frozenset(".!#$%&'*+/=?^_`{|}~-")
EMAIL_DOMAIN = ASCII_ALNUM | frozenset(".-")
HOME = re.compile(r"(?i)(?:/(?:home|Users)/[^\s/<>`\"']+(?:/[^\s<>`\"']*)?|[A-Z]:[\\/]Users[\\/][^\s\\/<>`\"']+(?:[\\/][^\s<>`\"']*)?)")
ACCOUNT = re.compile(r"(?i)\b(?:account[_ -]?id|aws[_ -]?account|账户\s*ID|账号\s*ID)[\s`\"']{0,8}[:=][\s`\"']{0,8}(?:[0-9]{6,20}|[a-f0-9]{24,64})\b")
SECRETS = (
    ("secret.private-key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
    ("secret.aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("secret.github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,255}|github_pat_[A-Za-z0-9_]{22,255})\b")),
    ("secret.gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,255}\b")),
    ("secret.slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,255}\b")),
    ("secret.google-api-key", re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b")),
    ("secret.stripe-key", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{16,255}\b")),
    ("secret.openai-like-key", re.compile(r"\bsk-(?:(?:proj|svcacct)-)?[A-Za-z0-9_-]{20,255}\b")),
    ("secret.credential-url", re.compile(r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@")),
)
ASSIGNMENT = re.compile(r"(?im)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|secret[_-]?key)[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_+./=-]{16,})")
BLOCK = re.compile(r"(?im)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|secret[_-]?key)[\"']?\s*:\s*[|>][-+]?\s*\n((?:[ \t]+[^\r\n]+(?:\r?\n|$)){1,8})")
PRIVACY_RULES = {"markdown.email", "markdown.user-home", "markdown.account-id", "filename.email"}
KINDS = {"third-party-contact", "license", "placeholder"}


@dataclass(frozen=True)
class Match:
    rule: str
    start: int
    value: str


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()


def email_matches(text: str, rule: str, path_mode: bool = False) -> Iterator[Match]:
    """Bounded work per @; no unbounded local-part/domain regex backtracking.

    Intentionally limited to ASCII unquoted local parts <=64 and domains <=253.
    Reject overlong tokens rather than recognizing a misleading substring.
    """
    local_chars = EMAIL_LOCAL - {"/"} if path_mode else EMAIL_LOCAL
    for at in re.finditer("@", text):
        center = at.start()
        start = center
        while start and center - start < 65 and text[start - 1] in local_chars:
            start -= 1
        if not 1 <= center - start <= 64:
            continue
        if start and (text[start - 1].isalnum() or text[start - 1] == "_"):
            continue
        end = center + 1
        while end < len(text) and end - center - 1 < 254 and text[end] in EMAIL_DOMAIN:
            end += 1
        if end < len(text) and (text[end] in EMAIL_DOMAIN or text[end].isalnum() or text[end] == "_"):
            continue
        domain = text[center + 1:end].rstrip(".")
        if not 3 <= len(domain) <= 253:
            continue
        labels = domain.split(".")
        if len(labels) < 2 or not 2 <= len(labels[-1]) <= 63 or not labels[-1].isascii() or not labels[-1].isalpha():
            continue
        if any(not label or len(label) > 63 or label[0] not in ASCII_ALNUM or label[-1] not in ASCII_ALNUM for label in labels):
            continue
        yield Match(rule, start, text[start:center + 1 + len(domain)])


def matches(text: str, markdown: bool, location: str = "content") -> Iterator[Match]:
    rules = list(SECRETS)
    if markdown and location == "content":
        rules += [("markdown.user-home", HOME), ("markdown.account-id", ACCOUNT)]
    for rule, pattern in rules:
        for m in pattern.finditer(text):
            yield Match(rule, m.start(), m.group())
    if markdown or location == "path":
        yield from email_matches(text, "filename.email" if location == "path" else "markdown.email", path_mode=location == "path")
    for m in ASSIGNMENT.finditer(text):
        counts = Counter(m.group(1))
        entropy = -sum((n / len(m.group(1))) * math.log2(n / len(m.group(1))) for n in counts.values())
        if entropy >= 3.0:
            yield Match("secret.credential-assignment", m.start(1), m.group(1))
    if location == "content":
        for m in BLOCK.finditer(text):
            value = "".join(m.group(1).split())
            if len(value) >= 16:
                counts = Counter(value)
                entropy = -sum((n / len(value)) * math.log2(n / len(value)) for n in counts.values())
                if entropy >= 3.0:
                    yield Match("secret.credential-block", m.start(1), m.group(1))


class PolicyError(Exception):
    """Never embed input values in error messages."""


def unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PolicyError("invalid-allowlist")
        result[key] = value
    return result


def open_directory(path: Path) -> int:
    """Open every ancestor with O_NOFOLLOW; never resolve away a symlink or '..'."""
    if ".." in path.parts:
        raise OSError("unsafe-path")
    absolute = path if path.is_absolute() else Path(os.getcwd()) / path
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in absolute.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_policy(path: Path) -> str:
    """Reject FIFO/device/socket/symlink policies before any read; bound bytes."""
    parent = open_directory(path.parent)
    fd = None
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 128 * 1024:
            raise PolicyError("invalid-allowlist")
        with os.fdopen(fd, "rb") as stream:
            fd = None
            data = stream.read(128 * 1024 + 1)
            after = os.fstat(stream.fileno())
        if len(data) > 128 * 1024 or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise PolicyError("invalid-allowlist")
        return data.decode("utf-8")
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def load_allowlist(path: Path | None) -> list[dict]:
    if path is None:
        return []
    try:
        raw = json.loads(read_policy(path), object_pairs_hook=unique_object)
        if not isinstance(raw, dict) or set(raw) != {"version", "allow"} or type(raw["version"]) is not int or raw["version"] != 1 or not isinstance(raw["allow"], list):
            raise PolicyError("invalid-allowlist")
        seen = set()
        for entry in raw["allow"]:
            required = {"path", "rule", "location", "match_sha256", "kind", "reason", "expires", "max_count"}
            if not isinstance(entry, dict) or set(entry) != required:
                raise PolicyError("invalid-allowlist")
            if any(not isinstance(entry[k], str) for k in required - {"max_count"}):
                raise PolicyError("invalid-allowlist")
            p = PurePosixPath(entry["path"])
            if not entry["path"] or p.is_absolute() or str(p) != entry["path"] or any(part in {"..", ".git"} for part in p.parts) or any(c in entry["path"] for c in "*?[]\\\x00\n\r"):
                raise PolicyError("invalid-allowlist")
            if entry["rule"] not in PRIVACY_RULES or entry["location"] not in {"path", "content"} or ((entry["rule"] == "filename.email") != (entry["location"] == "path")):
                raise PolicyError("invalid-allowlist")
            if entry["kind"] not in KINDS or len(entry["reason"].strip()) < 12:
                raise PolicyError("invalid-allowlist")
            if entry["rule"] in {"markdown.user-home", "markdown.account-id"} and entry["kind"] != "placeholder":
                raise PolicyError("invalid-allowlist")
            if not re.fullmatch(r"[a-f0-9]{64}", entry["match_sha256"]) or type(entry["max_count"]) is not int or not 1 <= entry["max_count"] <= 100:
                raise PolicyError("invalid-allowlist")
            today = dt.datetime.now(dt.timezone.utc).date()
            expiry = dt.date.fromisoformat(entry["expires"])
            if expiry < today:
                raise PolicyError("expired-allowlist")
            if expiry > today + dt.timedelta(days=180):
                raise PolicyError("invalid-allowlist")
            key = tuple(entry[k] for k in ("path", "rule", "location", "match_sha256"))
            if key in seen:
                raise PolicyError("invalid-allowlist")
            seen.add(key)
        return raw["allow"]
    except PolicyError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        raise PolicyError("invalid-allowlist") from None


def scan(root: Path, allow: list[dict] | None = None, max_file_bytes: int = 20 * 1024 * 1024, max_total_bytes: int = 512 * 1024 * 1024, max_files: int = 20000, max_directories: int = 20000, max_depth: int = 128, max_findings: int = 10000) -> dict:
    """Inspect an immutable/quiet snapshot; .git metadata is the only exclusion.

    .gitignore is deliberately NOT honored; tracked-but-ignored files still matter.
    Symlinks, special files, oversized files and failed reads make the result incomplete.
    Non-UTF8/NUL files receive byte-pattern checks AND an incomplete result.
    """
    result = {"version": REPORT_VERSION, "scope": "current-files-only", "status": "clean", "files_scanned": 0, "bytes_scanned": 0, "git_entries_excluded": 0, "allowances_used": 0, "findings": [], "errors": []}
    allow = allow or []
    used = Counter()
    allowed = {tuple(e[k] for k in ("path", "rule", "location", "match_sha256")): (i, e) for i, e in enumerate(allow)}

    stopped = False
    observed_files = 0
    observed_dirs = 1
    enumerated_entries = 0

    def error(code: str, rel: str = "") -> None:
        nonlocal stopped
        if len(result["errors"]) >= 10000:
            stopped = True
            if len(result["errors"]) == 10000:
                result["errors"].append({"code": "error-count-limit", "file_id": None})
        else:
            result["errors"].append({"code": code, "file_id": digest(rel) if rel else None})

    def inspect(text: str, rel: str, markdown: bool, location: str) -> None:
        nonlocal stopped
        # One bounded-width newline index per file, rather than rescanning the
        # whole prefix for every finding. Python array avoids millions of ints.
        newlines = array("I", (m.start() for m in re.finditer("\n", text))) if location == "content" else None
        file_id = digest(rel)
        for m in matches(text, markdown, location):
            item = allowed.get((rel, m.rule, location, digest(m.value))) if allowed else None
            if item and used[item[0]] < item[1]["max_count"]:
                used[item[0]] += 1
                result["allowances_used"] += 1
                continue
            if len(result["findings"]) >= max_findings:
                error("finding-count-limit")
                stopped = True
                return
            line_index = bisect_left(newlines, m.start) if newlines is not None else None
            line = line_index + 1 if line_index is not None else None
            column = m.start - (newlines[line_index - 1] if line_index else -1) if line_index is not None else None
            result["findings"].append({"rule": m.rule, "location": location, "file_id": file_id, "line": line, "column": column})

    def read_file(parent: int, name: str, rel: str, seen: os.stat_result) -> None:
        nonlocal stopped
        fd = None
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                error("special-file-not-scanned", rel)
                return
            if (before.st_dev, before.st_ino) != (seen.st_dev, seen.st_ino):
                error("entry-changed", rel)
                return
            if before.st_size > max_file_bytes:
                error("file-size-limit", rel)
                return
            if result["bytes_scanned"] + before.st_size > max_total_bytes:
                error("total-size-limit")
                stopped = True
                return
            with os.fdopen(fd, "rb") as stream:
                fd = None
                raw = stream.read(max_file_bytes + 1)
                after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                error("entry-changed", rel)
                return
            if len(raw) > max_file_bytes:
                error("file-size-limit", rel)
                return
            if result["bytes_scanned"] + len(raw) > max_total_bytes:
                error("total-size-limit")
                stopped = True
                return
            try:
                content = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                error("file-not-utf8", rel)
                content = raw.decode("latin-1")
            if "\x00" in content:
                error("file-contains-nul", rel)
            inspect(content, rel, Path(name).suffix.lower() in MARKDOWN, "content")
            if not stopped:
                result["files_scanned"] += 1
                result["bytes_scanned"] += len(raw)
        except (OSError, ValueError):
            error("file-read-failed", rel)
        finally:
            if fd is not None:
                os.close(fd)

    def walk(parent: int, prefix: str, depth: int) -> None:
        nonlocal observed_files, observed_dirs, enumerated_entries, stopped
        try:
            entries = []
            with os.scandir(parent) as iterator:
                for entry in iterator:
                    enumerated_entries += 1
                    entries.append(entry.name)
                    if enumerated_entries > max_files + max_directories:
                        error("directory-entry-limit", prefix)
                        stopped = True
                        return
            for name in sorted(entries):
                if stopped:
                    return
                if name == ".git":
                    result["git_entries_excluded"] += 1
                    continue
                rel = prefix + "/" + name if prefix else name
                inspect(rel, rel, False, "path")
                if stopped:
                    return
                try:
                    seen = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if stat.S_ISDIR(seen.st_mode):
                        observed_dirs += 1
                        if observed_dirs > max_directories or depth + 1 > max_depth:
                            error("directory-count-or-depth-limit", rel)
                            stopped = True
                            return
                        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                        try:
                            opened = os.fstat(child)
                            if (seen.st_dev, seen.st_ino) != (opened.st_dev, opened.st_ino):
                                error("entry-changed", rel)
                            else:
                                walk(child, rel, depth + 1)
                        finally:
                            os.close(child)
                    else:
                        observed_files += 1
                        if observed_files > max_files:
                            error("file-count-limit")
                            stopped = True
                            return
                        if stat.S_ISLNK(seen.st_mode):
                            error("symlink-not-scanned", rel)
                        elif not stat.S_ISREG(seen.st_mode):
                            error("special-file-not-scanned", rel)
                        else:
                            read_file(parent, name, rel, seen)
                except (OSError, ValueError):
                    error("entry-read-failed", rel)
        except (OSError, ValueError):
            error("directory-read-failed", prefix)

    if min(max_file_bytes, max_total_bytes, max_files, max_directories, max_depth, max_findings) <= 0:
        error("invalid-limit")
    else:
        root_fd = None
        try:
            root_fd = open_directory(root)
            walk(root_fd, "", 0)
        except (OSError, ValueError):
            error("invalid-root")
        finally:
            if root_fd is not None:
                os.close(root_fd)
    for i in range(len(allow)):
        if not used[i]:
            error("unused-allowance")
    if not result["files_scanned"] and not result["errors"]:
        error("empty-snapshot")
    result["status"] = "incomplete" if result["errors"] else "findings" if result["findings"] else "clean"
    return result


class RedactedParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print(json.dumps({"version": REPORT_VERSION, "status": "incomplete", "errors": [{"code": "invalid-arguments"}]}))
        raise SystemExit(2)


def main() -> int:
    parser = RedactedParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--allowlist", type=Path)
    args = parser.parse_args()
    try:
        report = scan(args.root, load_allowlist(args.allowlist))
    except PolicyError as exc:
        report = {"version": REPORT_VERSION, "status": "incomplete", "errors": [{"code": str(exc)}]}
    except Exception:
        report = {"version": REPORT_VERSION, "status": "incomplete", "errors": [{"code": "scan-failed"}]}
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return {"clean": 0, "findings": 1, "incomplete": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
