"""Offline, synthetic Git object fixtures; no repository hooks or app code run."""
import datetime as dt
import hashlib
import importlib.util
import json
import marshal
import os
from pathlib import Path
import shutil
import subprocess
import struct
import sys
import tempfile
import unittest
import zlib
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "markdown_privacy_gate.py"
spec = importlib.util.spec_from_file_location("markdown_privacy_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
exec(compile(SCRIPT.read_bytes(), str(SCRIPT), "exec"), gate.__dict__)
EMAIL = "fictional.person" + "@" + "example.invalid"
TOKEN = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="markdown-object-fixture-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "--quiet", "--template=")

    def git(self, *args, data=b""):
        env = gate.git_environment()
        env.update({"GIT_AUTHOR_NAME": "Synthetic Fixture", "GIT_COMMITTER_NAME": "Synthetic Fixture", "GIT_AUTHOR_EMAIL": "fixture" + "@" + "example.invalid", "GIT_COMMITTER_EMAIL": "fixture" + "@" + "example.invalid", "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z"})
        proc = subprocess.run([shutil.which("git", path=os.defpath), "-c", "core.hooksPath=/dev/null", "-C", str(self.repo), *args], input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=10)
        self.assertEqual(proc.returncode, 0, "Synthetic Git fixture preparation failed")
        return proc.stdout.strip().decode("ascii")

    def blob(self, raw):
        if isinstance(raw, str):
            raw = raw.encode()
        return self.git("hash-object", "-w", "--stdin", data=raw)

    def tree(self, files):
        dirs = {"": []}
        for path, value in files.items():
            parent, _, name = path.rpartition("/")
            while parent not in dirs:
                dirs[parent] = []
                parent = parent.rpartition("/")[0]
            parent = path.rpartition("/")[0]
            if isinstance(value, tuple):
                mode, kind, oid = value
            else:
                mode, kind, oid = "100644", "blob", self.blob(value)
            dirs[parent].append((name, mode, kind, oid))
        for directory in sorted(dirs, key=lambda s: (s.count("/") + bool(s)), reverse=True):
            records = b"".join((mode + " " + kind + " " + oid + "\t" + name).encode() + b"\0" for name, mode, kind, oid in dirs[directory])
            oid = self.git("mktree", "-z", "--missing", data=records)
            if directory:
                parent, _, name = directory.rpartition("/")
                dirs[parent].append((name, "040000", "tree", oid))
        return oid

    def commit(self, tree):
        return self.git("commit-tree", tree, data=b"Synthetic fixture\n")

    def cli(self, revision, *args, repo=None, script=SCRIPT):
        p = subprocess.run([sys.executable, "-B", "-I", str(script), "--repo", str(repo or self.repo), "--revision", revision, *args], capture_output=True, text=True, timeout=10)
        self.assertEqual(p.stderr, "")
        r = json.loads(p.stdout)
        self.assertEqual(p.returncode, {"clean": 0, "findings": 1, "incomplete": 2}[r["status"]])
        return p.returncode, r, p.stdout

    def check(self, files):
        return gate.check(self.repo, self.tree(files))

    def test_clean_exact_commit_and_manifest(self):
        tree = self.tree({"README.md": "# Public documentation\n"})
        revision = self.commit(tree)
        code, report, _ = self.cli(revision)
        self.assertEqual(code, 0)
        self.assertEqual(report["tree"], tree)
        self.assertEqual(report["revision_type"], "commit")
        self.assertEqual(report["markdown_blobs"], 1)
        self.assertEqual(report["manifest"][0]["blob"], self.blob("# Public documentation\n"))

    def test_nested_uppercase_md_mdx_and_gitignored_tracked(self):
        report = self.check({".gitignore": "docs/\n", "docs/a.MD": EMAIL, "docs/deep/b.MdX": EMAIL, "notes.markdown": EMAIL})
        self.assertEqual(report["markdown_blobs"], 2)
        self.assertEqual(len(report["gate"]["findings"]), 2)

    def test_non_markdown_binary_and_secret_not_in_declared_scope(self):
        report = self.check({"README.md": "clean", "image.bin": b"\0\xff", "config.py": TOKEN})
        self.assertEqual(report["status"], "clean")
        self.assertEqual(report["inventory_entries"], 3)
        self.assertEqual(report["markdown_blobs"], 1)

    def test_worktree_changes_and_untracked_files_not_read(self):
        tree = self.tree({"README.md": EMAIL})
        (self.repo / "README.md").write_text("clean working tree")
        (self.repo / "extra.md").write_text("not a Git object")
        self.assertEqual(gate.check(self.repo, tree)["status"], "findings")
        self.assertEqual(gate.check(self.repo, tree)["markdown_blobs"], 1)

    def test_branch_abbreviated_and_option_revisions_rejected(self):
        tree = self.tree({"README.md": "clean"})
        for value in ("HEAD", "main", tree[:12], "--help", "a" * 39):
            with self.subTest(value=value):
                self.assertEqual(self.cli(value)[0], 2)

    def test_blob_revision_rejected(self):
        self.assertEqual(self.cli(self.blob("clean"))[0], 2)

    def test_no_markdown_is_explicit_incomplete(self):
        code, report, _ = self.cli(self.tree({"code.py": "pass"}))
        self.assertEqual(code, 2)
        self.assertEqual(report["errors"][0]["code"], "no-tracked-markdown")

    def test_symlink_even_non_markdown_rejected(self):
        tree = self.tree({"README.md": "clean", "link": ("120000", "blob", self.blob("README.md"))})
        self.assertEqual(self.cli(tree)[0], 2)

    def test_submodule_even_non_markdown_rejected(self):
        sub = self.commit(self.tree({"sub.md": "clean"}))
        tree = self.tree({"README.md": "clean", "module": ("160000", "commit", sub)})
        self.assertEqual(self.cli(tree)[0], 2)

    def test_missing_markdown_blob_fails_closed(self):
        tree = self.tree({"README.md": "clean"})
        oid = self.blob("clean")
        (self.repo / ".git" / "objects" / oid[:2] / oid[2:]).unlink()
        self.assertEqual(self.cli(tree)[0], 2)

    def test_missing_promisor_blob_does_not_lazy_fetch_or_run_helper(self):
        tree = self.tree({"README.md": "clean"})
        oid = self.blob("clean")
        (self.repo / ".git" / "objects" / oid[:2] / oid[2:]).unlink()
        sentinel = self.root / "unexpected-fetch-helper"
        self.git("config", "extensions.partialClone", "origin")
        self.git("config", "remote.origin.promisor", "true")
        self.git("config", "remote.origin.url", "ext::/bin/touch " + str(sentinel))
        self.git("config", "protocol.ext.allow", "always")
        self.assertEqual(self.cli(tree)[0], 2)
        self.assertFalse(sentinel.exists())

    def test_missing_subtree_fails_closed(self):
        tree = self.tree({"docs/README.md": "clean"})
        subtree = self.git("rev-parse", tree + ":docs")
        (self.repo / ".git" / "objects" / subtree[:2] / subtree[2:]).unlink()
        self.assertEqual(self.cli(tree)[0], 2)

    def test_invalid_utf8_and_nul_markdown_incomplete(self):
        for data in (b"\xff", b"hello\0world"):
            self.assertEqual(self.cli(self.tree({"README.md": data}))[0], 2)

    def test_markdown_lfs_pointer_is_incomplete_without_fetching(self):
        pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"0" * 64 + b"\nsize 100\n"
        for data in (pointer, pointer.replace(b"\n", b"\r\n"), b"\xef\xbb\xbf" + pointer):
            code, report, _ = self.cli(self.tree({"README.md": data}))
            self.assertEqual(code, 2)
            self.assertEqual(report["errors"][0]["code"], "lfs-pointer-not-materialized")

    def test_oversized_markdown_incomplete_not_skipped(self):
        self.assertEqual(self.cli(self.tree({"README.md": b"a" * (gate.MAX_BLOB_BYTES + 1)}))[0], 2)

    def test_count_and_total_budgets_fail_closed(self):
        tree = self.tree({"a.md": "123456", "b.md": "abcdef"})
        with mock.patch.object(gate, "MAX_DOCUMENTS", 1):
            with self.assertRaisesRegex(gate.GateError, "markdown-count-limit"):
                gate.check(self.repo, tree)
        with mock.patch.object(gate, "MAX_TOTAL_BYTES", 10):
            with self.assertRaisesRegex(gate.GateError, "markdown-total-size-limit"):
                gate.check(self.repo, tree)

    def test_inventory_budget_fails_closed(self):
        tree = self.tree({"a.md": "clean", "b.py": "pass"})
        with mock.patch.object(gate, "MAX_ENTRIES", 1):
            with self.assertRaisesRegex(gate.GateError, "tree-entry-limit"):
                gate.check(self.repo, tree)

    def test_unsafe_paths_and_nonutf8_names_rejected(self):
        for path in (b"../note.md", b"/note.md", b".git/note.md", b"a//note.md", b"a/./note.md", b"\xff.md"):
            with self.assertRaises(gate.GateError):
                gate.safe_path(path)

    def test_filename_contact_and_body_secret_redacted(self):
        filename = EMAIL + ".md"
        code, report, output = self.cli(self.tree({filename: TOKEN}))
        self.assertEqual(code, 1)
        for value in (EMAIL, TOKEN, filename, str(self.repo)):
            self.assertNotIn(value, output)
        self.assertEqual(len(report["gate"]["findings"]), 2)

    def test_newline_tab_filename_safe_and_redacted(self):
        name = "odd\n\tname.md"
        code, report, output = self.cli(self.tree({name: "clean"}))
        self.assertEqual(code, 0)
        self.assertEqual(report["manifest"][0]["file_id"], hashlib.sha256(name.encode()).hexdigest())
        self.assertNotIn("odd", output)

    def test_policy_read_from_same_exact_tree_not_worktree(self):
        policy = {"version": 1, "allow": [{"path": "README.md", "rule": "markdown.email", "location": "content", "match_sha256": hashlib.sha256(EMAIL.encode()).hexdigest(), "kind": "placeholder", "reason": "Reserved synthetic fixture address", "expires": (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=30)).isoformat(), "max_count": 1}]}
        tree = self.tree({"README.md": EMAIL, "policy.json": json.dumps(policy)})
        (self.repo / "policy.json").write_text("malformed worktree policy")
        code, report, output = self.cli(tree, "--allowlist", "policy.json")
        self.assertEqual(code, 0)
        self.assertEqual(report["gate"]["allowances_used"], 1)
        self.assertNotIn(EMAIL, output)

    def test_missing_or_invalid_tracked_policy_fails(self):
        for files in ({"README.md": "clean"}, {"README.md": "clean", "policy.json": "not JSON"}):
            self.assertEqual(self.cli(self.tree(files), "--allowlist", "policy.json")[0], 2)

    def test_repository_symlink_ancestor_rejected(self):
        tree = self.tree({"README.md": "clean"})
        link = self.root / "link"
        link.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.cli(tree, repo=link / "repo")[0], 2)

    def test_missing_scanner_dependency_fails_redacted(self):
        isolated = self.root / "standalone.py"
        isolated.write_bytes(SCRIPT.read_bytes())
        code, report, output = self.cli(self.tree({"README.md": "clean"}), script=isolated)
        self.assertEqual(code, 2)
        self.assertEqual(report["errors"][0]["code"], "scanner-unavailable")
        self.assertNotIn(str(isolated), output)

    def test_git_replace_does_not_substitute_exact_blob(self):
        original = self.blob(EMAIL)
        replacement = self.blob("clean")
        tree = self.tree({"README.md": ("100644", "blob", original)})
        self.git("replace", original, replacement)
        self.assertEqual(gate.check(self.repo, tree)["status"], "findings")

    def test_local_filters_hooks_fsmonitor_and_repo_scripts_not_run(self):
        sentinel = self.root / "would-have-run"
        command = "touch " + str(sentinel)
        self.git("config", "core.fsmonitor", command)
        self.git("config", "filter.fixture.smudge", command)
        hook = self.repo / ".git" / "hooks" / "post-checkout"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text("#!/bin/sh\n" + command + "\n")
        hook.chmod(0o700)
        tree = self.tree({"README.md": "clean", ".gitattributes": "*.md filter=fixture", "scripts/payload.py": "raise RuntimeError('must not execute')"})
        self.assertEqual(gate.check(self.repo, tree)["status"], "clean")
        self.assertFalse(sentinel.exists())

    def test_git_limits_and_dependency_failure(self):
        tree = self.tree({"README.md": "clean"})
        with self.assertRaisesRegex(gate.GateError, "git-output-limit"):
            gate.run_git(self.repo, ["cat-file", "-p", tree], limit=1)
        with mock.patch.object(gate, "GIT_TIMEOUT", 0):
            with self.assertRaisesRegex(gate.GateError, "git-time-limit"):
                gate.run_git(self.repo, ["cat-file", "-t", tree])
        with mock.patch.object(gate.shutil, "which", return_value=None):
            with self.assertRaisesRegex(gate.GateError, "git-unavailable"):
                gate.run_git(self.repo, ["cat-file", "-t", tree])

    def test_blob_hash_verification(self):
        oid = self.blob("original")
        entries = [{"path": "README.md", "blob": oid}]
        responses = [(oid + " blob 8\n").encode(), (oid + " blob 8\n").encode() + b"tampered\n"]
        with mock.patch.object(gate, "run_git", side_effect=responses):
            with self.assertRaisesRegex(gate.GateError, "blob-digest-mismatch"):
                gate.blobs(self.repo, entries)

    def test_corrupted_tree_object_fails_digest_check(self):
        tree = self.tree({"README.md": EMAIL})
        replacement = self.tree({"README.md": "clean"})
        source = self.repo / ".git" / "objects" / replacement[:2] / replacement[2:]
        target = self.repo / ".git" / "objects" / tree[:2] / tree[2:]
        target.chmod(0o600)  # This test owns the disposable synthetic Git object.
        target.write_bytes(source.read_bytes())
        code, report, _ = self.cli(tree)
        self.assertEqual(code, 2)
        self.assertIn(report["errors"][0]["code"], {"tree-digest-mismatch", "git-read-failed"})

    def test_corrupted_commit_object_fails_digest_check(self):
        revision = self.commit(self.tree({"README.md": "clean"}))
        target = self.repo / ".git" / "objects" / revision[:2] / revision[2:]
        raw = zlib.decompress(target.read_bytes()).replace(b"Synthetic fixture", b"Different fixture")
        target.chmod(0o600)  # Git intentionally creates loose objects read-only.
        target.write_bytes(zlib.compress(raw))
        code, report, _ = self.cli(revision)
        self.assertEqual(code, 2)
        self.assertIn(report["errors"][0]["code"], {"commit-digest-mismatch", "git-read-failed"})

    def test_repository_bytecode_cannot_replace_reviewed_scanner_source(self):
        isolated = self.root / "gate"
        isolated.mkdir()
        adapter = isolated / SCRIPT.name
        adapter.write_bytes(SCRIPT.read_bytes())
        scanner = isolated / "privacy_gate.py"
        scanner.write_bytes(SCRIPT.with_name("privacy_gate.py").read_bytes())
        sentinel = self.root / "unexpected-bytecode"
        payload = compile("from pathlib import Path\nPath(" + repr(str(sentinel)) + ").write_text('ran')", str(scanner), "exec")
        info = scanner.stat()
        cache = Path(importlib.util.cache_from_source(str(scanner)))
        cache.parent.mkdir()
        cache.write_bytes(importlib.util.MAGIC_NUMBER + b"\0" * 4 + struct.pack("<II", int(info.st_mtime), info.st_size) + marshal.dumps(payload))
        code, _, _ = self.cli(self.tree({"README.md": "clean"}), script=adapter)
        self.assertEqual(code, 0)
        self.assertFalse(sentinel.exists())

    def test_directory_with_markdown_suffix_is_not_a_document(self):
        report = self.check({"folder.md/README.md": "clean", "folder.md/code.py": "pass"})
        self.assertEqual(report["markdown_blobs"], 1)
        self.assertEqual(report["status"], "clean")

    def test_temporary_exports_cleaned_on_success_and_error(self):
        temp_root = self.root / "exports"
        temp_root.mkdir()
        real_temp = tempfile.TemporaryDirectory
        def isolated_temp(*args, **kwargs):
            return real_temp(*args, dir=temp_root, **kwargs)
        with mock.patch.object(gate.tempfile, "TemporaryDirectory", side_effect=isolated_temp):
            gate.check(self.repo, self.tree({"README.md": "clean"}))
            with self.assertRaises(gate.GateError):
                gate.check(self.repo, self.tree({"README.md": "clean", "policy.json": "bad"}), "policy.json")
        self.assertEqual(list(temp_root.iterdir()), [])

    def test_invalid_cli_is_redacted(self):
        proc = subprocess.run([sys.executable, "-B", "-I", str(SCRIPT), "--unexpected", EMAIL], capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn(EMAIL, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
