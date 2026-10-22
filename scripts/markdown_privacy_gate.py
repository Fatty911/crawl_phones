#!/usr/bin/env python3
"""Read exact Git objects for all tracked .md/.mdx files; never read worktree text."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import time

MAX_ENTRIES = 40000
MAX_DOCUMENTS = 1000
MAX_BLOB_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_TREE_BYTES = 8 * 1024 * 1024
MAX_COMMIT_BYTES = 1024 * 1024
GIT_TIMEOUT = 15
SUFFIXES = {".md", ".mdx"}


class GateError(Exception):
    pass


def git_environment() -> dict:
    return {"PATH": os.defpath, "LC_ALL": "C", "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1"}


def run_git(repo: Path, args: list[str], *, data: bytes = b"", limit: int = MAX_TREE_BYTES) -> bytes:
    """Bound stdout/stderr/time; no shell, hooks, filters, prompts or lazy fetch."""
    if not args or args[0] not in {"cat-file", "rev-parse", "ls-tree"}:
        raise GateError("unsupported-git-operation")
    executable = shutil.which("git", path=os.defpath)
    if executable is None:
        raise GateError("git-unavailable")
    command = [executable, "--no-lazy-fetch", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "protocol.allow=never", "-C", str(repo), *args]
    proc = None
    output = bytearray()
    error_bytes = 0
    try:
        with tempfile.TemporaryFile() as source, selectors.DefaultSelector() as selector:
            source.write(data)
            source.seek(0)
            proc = subprocess.Popen(command, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=git_environment(), start_new_session=True)
            for stream in (proc.stdout, proc.stderr):
                selector.register(stream, selectors.EVENT_READ)
            deadline = time.monotonic() + GIT_TIMEOUT
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise GateError("git-time-limit")
                for key, _ in selector.select(min(remaining, 0.25)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if key.fileobj is proc.stdout:
                        if len(output) + len(chunk) > limit:
                            raise GateError("git-output-limit")
                        output.extend(chunk)
                    else:
                        error_bytes += len(chunk)
                        if error_bytes > 4096:
                            raise GateError("git-error-output-limit")
            remaining = deadline - time.monotonic()
            if remaining <= 0 or proc.wait(timeout=remaining) != 0:
                raise GateError("git-read-failed")
        return bytes(output)
    except (OSError, subprocess.SubprocessError):
        raise GateError("git-read-failed") from None
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            for stream in (proc.stdout, proc.stderr):
                if stream:
                    stream.close()


def load_scanner():
    path = Path(__file__).with_name("privacy_gate.py")
    try:
        spec = importlib.util.spec_from_file_location("_reviewed_privacy_gate", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        # Execute only the reviewed source, never a repository-supplied .pyc.
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
        return module
    except Exception:
        raise GateError("scanner-unavailable") from None


def safe_path(raw: bytes) -> str:
    try:
        name = raw.decode("utf-8")
    except UnicodeError:
        raise GateError("unsupported-path-encoding") from None
    p = PurePosixPath(name)
    if not name or p.is_absolute() or str(p) != name or any(part in {".", ".."} or part.lower() == ".git" for part in p.parts):
        raise GateError("unsafe-tree-path")
    return name


def inventory(repo: Path, revision: str) -> tuple[str, str, list[dict]]:
    if not re.fullmatch(r"(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})", revision):
        raise GateError("exact-object-sha-required")
    revision = revision.lower()
    kind = run_git(repo, ["cat-file", "-t", revision], limit=100).strip().decode("ascii")
    if kind not in {"commit", "tree"}:
        raise GateError("commit-or-tree-required")
    tree = run_git(repo, ["rev-parse", "--verify", "--end-of-options", revision + "^{tree}"], limit=100).strip().decode("ascii")
    if not re.fullmatch(r"[a-f0-9]{" + str(len(revision)) + "}", tree):
        raise GateError("invalid-tree-object")
    algorithm = hashlib.sha1 if len(revision) == 40 else hashlib.sha256
    if kind == "commit":
        commit = run_git(repo, ["cat-file", "commit", revision], limit=MAX_COMMIT_BYTES)
        if algorithm(b"commit " + str(len(commit)).encode() + b"\0" + commit).hexdigest() != revision or commit.split(b"\n", 1)[0] != b"tree " + tree.encode():
            raise GateError("commit-digest-mismatch")
    raw = run_git(repo, ["ls-tree", "-r", "-t", "--full-tree", "-z", tree])
    if raw and not raw.endswith(b"\0"):
        raise GateError("incomplete-tree-inventory")
    entries = []
    seen = set()
    for record in raw.split(b"\0")[:-1]:
        if len(entries) >= MAX_ENTRIES:
            raise GateError("tree-entry-limit")
        try:
            metadata, path = record.split(b"\t", 1)
            mode, object_type, oid = metadata.decode("ascii").split(" ")
        except (ValueError, UnicodeError):
            raise GateError("invalid-tree-inventory") from None
        name = safe_path(path)
        if name in seen or not re.fullmatch(r"[a-f0-9]{" + str(len(revision)) + "}", oid):
            raise GateError("invalid-tree-inventory")
        seen.add(name)
        # Submodule contents are not inventoried; symlinks can hide doc targets.
        if (mode, object_type) not in {("100644", "blob"), ("100755", "blob"), ("040000", "tree")}:
            raise GateError("unsupported-tree-entry")
        entries.append({"path": name, "mode": mode, "blob": oid, "type": object_type})
    # Rebuild every canonical tree object to bind the complete flattened inventory
    # to the requested immutable root, including empty trees and directory names.
    by_path = {entry["path"]: entry for entry in entries}
    groups = {"": []}
    for entry in entries:
        parent, _, name = entry["path"].rpartition("/")
        if parent and (parent not in by_path or by_path[parent]["type"] != "tree"):
            raise GateError("incomplete-tree-inventory")
        groups.setdefault(parent, []).append((name, entry))
        if entry["type"] == "tree":
            groups.setdefault(entry["path"], [])
    for parent, children in groups.items():
        ordered = sorted(children, key=lambda pair: (pair[0] + ("/" if pair[1]["type"] == "tree" else "")).encode("utf-8"))
        content = b"".join((entry["mode"].lstrip("0") + " " + name).encode("utf-8") + b"\0" + bytes.fromhex(entry["blob"]) for name, entry in ordered)
        expected = by_path[parent]["blob"] if parent else tree
        if algorithm(b"tree " + str(len(content)).encode() + b"\0" + content).hexdigest() != expected:
            raise GateError("tree-digest-mismatch")
    return kind, tree, [entry for entry in entries if entry["type"] == "blob"]


def blobs(repo: Path, entries: list[dict]) -> dict[str, bytes]:
    query = "".join(entry["blob"] + "\n" for entry in entries).encode("ascii")
    checked = run_git(repo, ["cat-file", "--batch-check"], data=query, limit=MAX_DOCUMENTS * 100 + 1000).splitlines()
    if len(checked) != len(entries):
        raise GateError("missing-blob")
    total = 0
    for entry, line in zip(entries, checked):
        try:
            oid, kind, length = line.decode("ascii").split(" ")
            size = int(length)
        except (ValueError, UnicodeError):
            raise GateError("missing-blob") from None
        if oid != entry["blob"] or kind != "blob" or size < 0:
            raise GateError("missing-blob")
        if size > MAX_BLOB_BYTES:
            raise GateError("markdown-size-limit")
        entry["bytes"] = size
        total += size
    if total > MAX_TOTAL_BYTES:
        raise GateError("markdown-total-size-limit")
    output = run_git(repo, ["cat-file", "--batch"], data=query, limit=total + len(entries) * 100 + 1000)
    offset = 0
    result = {}
    for entry in entries:
        end = output.find(b"\n", offset)
        expected = (entry["blob"] + " blob " + str(entry["bytes"])).encode("ascii")
        if end < 0 or output[offset:end] != expected:
            raise GateError("blob-protocol-error")
        start = end + 1
        end = start + entry["bytes"]
        data = output[start:end]
        if len(data) != entry["bytes"] or output[end:end + 1] != b"\n":
            raise GateError("missing-blob")
        algorithm = hashlib.sha1 if len(entry["blob"]) == 40 else hashlib.sha256
        if algorithm(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() != entry["blob"]:
            raise GateError("blob-digest-mismatch")
        first_line = data.removeprefix(b"\xef\xbb\xbf").split(b"\n", 1)[0].rstrip(b"\r")
        if first_line.startswith(b"version https://git-lfs.github.com/spec/"):
            # Object text is only a pointer; fetching/smudging is deliberately off.
            raise GateError("lfs-pointer-not-materialized")
        result[entry["path"]] = data
        offset = end + 1
    if offset != len(output):
        raise GateError("blob-protocol-error")
    return result


def check(repo: Path, revision: str, allowlist: str | None = None) -> dict:
    scanner = load_scanner()
    # Reject symlink ancestors and traversal in the repository location itself.
    try:
        fd = scanner.open_directory(repo)
        os.close(fd)
    except (OSError, ValueError):
        raise GateError("invalid-repository-path") from None
    kind, tree, entries = inventory(repo, revision)
    selected = [e for e in entries if PurePosixPath(e["path"]).suffix.lower() in SUFFIXES]
    if not selected:
        raise GateError("no-tracked-markdown")
    if len(selected) > MAX_DOCUMENTS:
        raise GateError("markdown-count-limit")
    requested = list(selected)
    if allowlist is not None:
        policy_name = safe_path(allowlist.encode("utf-8"))
        policy = next((e for e in entries if e["path"] == policy_name), None)
        if policy is None:
            raise GateError("tracked-policy-missing")
        if policy not in requested:
            requested.append(policy)
    content = blobs(repo, requested)
    with tempfile.TemporaryDirectory(prefix="md-privacy-export-") as directory:
        temp = Path(directory)
        export = temp / "snapshot"
        export.mkdir()
        for entry in selected:
            target = export / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(content[entry["path"]])
        allow = []
        if allowlist is not None:
            policy_file = temp / "policy.json"
            policy_file.write_bytes(content[policy_name])
            try:
                allow = scanner.load_allowlist(policy_file)
            except scanner.PolicyError:
                raise GateError("invalid-tracked-policy") from None
        report = scanner.scan(export, allow=allow, max_file_bytes=MAX_BLOB_BYTES, max_total_bytes=MAX_TOTAL_BYTES, max_files=MAX_DOCUMENTS)
        if report["files_scanned"] != len(selected) and report["status"] != "incomplete":
            raise GateError("materialization-count-mismatch")
    manifest = [{"file_id": scanner.digest(e["path"]), "blob": e["blob"], "mode": e["mode"], "bytes": e["bytes"]} for e in selected]
    return {"version": 1, "scope": "all-tracked-md-mdx-at-exact-object", "revision": revision.lower(), "revision_type": kind, "tree": tree, "inventory_entries": len(entries), "markdown_blobs": len(selected), "manifest": manifest, "status": report["status"], "gate": report}


class RedactedParser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"version": 1, "status": "incomplete", "errors": [{"code": "invalid-arguments"}]}))
        raise SystemExit(2)


def main() -> int:
    parser = RedactedParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--revision", required=True, help="Full immutable commit or tree object ID; never a branch/ref")
    parser.add_argument("--allowlist", help="Repository-relative policy path read from the same exact object, not the worktree")
    args = parser.parse_args()
    try:
        report = check(args.repo, args.revision, args.allowlist)
    except GateError as exc:
        report = {"version": 1, "scope": "all-tracked-md-mdx-at-exact-object", "status": "incomplete", "errors": [{"code": str(exc)}]}
    except Exception:
        report = {"version": 1, "scope": "all-tracked-md-mdx-at-exact-object", "status": "incomplete", "errors": [{"code": "adapter-failed"}]}
    print(json.dumps(report, sort_keys=True, ensure_ascii=True))
    return {"clean": 0, "findings": 1, "incomplete": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
