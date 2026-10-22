"""Synthetic offline fixtures only; no real identities, credentials or repo code."""
import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "privacy_gate.py"
spec = importlib.util.spec_from_file_location("privacy_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
exec(compile(SCRIPT.read_bytes(), str(SCRIPT), "exec"), gate.__dict__)

# Assemble synthetic strings, so this test source is not itself a token fixture.
CONTACT = "support" + "@" + "example.org"
PERSON = "fictional.person" + "@" + "invalid.test"
TOKEN = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
HOME = "/" + "Users/fictional-person/work/project"
GENERIC = "A1b2C3d4E5f6G7h8I9j0K1l2"


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="privacy-fixtures-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, name, content):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode())
        return p

    def report(self, **kwargs):
        return gate.scan(self.root, **kwargs)

    def rules(self, report):
        return {f["rule"] for f in report["findings"]}

    def allowance(self, path="README.md", rule="markdown.email", value=CONTACT, **overrides):
        result = {"path": path, "rule": rule, "location": "content", "match_sha256": gate.digest(value), "kind": "third-party-contact", "reason": "Intentional public vendor support contact", "expires": (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=30)).isoformat(), "max_count": 1}
        result.update(overrides)
        return result

    def load(self, entries):
        return gate.load_allowlist(self.put("allowlist.json", json.dumps({"version": 1, "allow": entries})))

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", "-I", str(SCRIPT), "--root", str(self.root), *args], capture_output=True, text=True, timeout=10, check=False)

    def test_email_in_markdown_code_fence_mailto_and_mdx(self):
        for name, text in [("README.md", "````text\n" + PERSON + "\n````"), ("docs/Page.MDX", "[contact](mailto:" + PERSON + ")")]:
            self.put(name, text)
        r = self.report()
        self.assertEqual(r["status"], "findings")
        self.assertEqual(len(r["findings"]), 2)
        self.assertEqual(self.rules(r), {"markdown.email"})

    def test_markdown_only_for_content_email(self):
        self.put("module.py", CONTACT)
        self.assertEqual(self.report()["status"], "clean")

    def test_user_home_paths_cross_platform(self):
        paths = [HOME, "/" + "home/fictional-person/code", "C:" + "\\Users\\fictional-person\\project"]
        self.put("README.markdown", "\n".join(paths))
        self.assertEqual(len(self.report()["findings"]), 3)

    def test_account_identifier_context_not_arbitrary_numbers(self):
        self.put("README.md", "account" + "_id = " + "abcdef12" * 4 + "\nMetrics: 123456789012\n")
        self.assertEqual(self.rules(self.report()), {"markdown.account-id"})

    def test_low_false_positive_baseline(self):
        self.put("README.md", "# Setup\nUse ${HOME}, <REPOSITORY_ROOT>, @scope/package, docs/run.md.\nVersion 1.2.3; count 123456789012.\n")
        self.assertEqual(self.report()["status"], "clean")

    def test_placeholder_email_not_globally_exempt(self):
        self.put("README.md", CONTACT)
        self.assertIn("markdown.email", self.rules(self.report()))
        allow = self.load([self.allowance(kind="placeholder", reason="Reserved-domain example in installation guide")])
        self.assertEqual(self.report(allow=allow)["status"], "clean")

    def test_common_provider_secrets_in_any_file_type(self):
        fixtures = [TOKEN, "AK" + "IA" + "A1B2C3D4E5F6G7H8", "gl" + "pat-" + GENERIC, "xox" + "b-" + GENERIC, "AI" + "za" + "A" * 35, "sk" + "_live_" + GENERIC, "sk" + "-proj-" + GENERIC, "github" + "_pat_" + GENERIC]
        for i, fixture in enumerate(fixtures):
            self.put(f"data/{i}.json", fixture)
        self.assertEqual(len(self.report()["findings"]), len(fixtures))

    def test_private_key_multiline_and_escaped_newlines(self):
        marker = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
        self.put("id.key", marker + "\n" + GENERIC + "\n-----END " + "OPENSSH PRIVATE KEY-----")
        self.put("config.json", json.dumps({"key": marker + "\n" + GENERIC}))
        self.assertEqual(self.rules(self.report()), {"secret.private-key"})
        self.assertEqual(len(self.report()["findings"]), 2)

    def test_credential_assignments_yaml_blocks_and_urls(self):
        self.put("config.txt", 'api' + '_key = "' + GENERIC + '"\nclient' + '_secret: |\n  ' + GENERIC + '\n  ' + GENERIC + '\n')
        self.put("connection.ini", "https://fixture-user:" + GENERIC + "@service.invalid")
        self.assertEqual(self.rules(self.report()), {"secret.credential-assignment", "secret.credential-block", "secret.credential-url"})

    def test_low_entropy_placeholders_are_not_generic_secret_hits(self):
        self.put("settings.ini", "api" + "_key = " + "x" * 32)
        self.assertEqual(self.report()["status"], "clean")

    def test_gitignore_is_not_a_bypass(self):
        self.put(".gitignore", "secret.txt\n*.md\n.cache/\n")
        self.put("secret.txt", TOKEN)
        self.put(".cache/hidden.md", PERSON)
        self.assertEqual(self.rules(self.report()), {"secret.github-token", "markdown.email"})

    def test_only_git_metadata_is_excluded(self):
        self.put(".git/config", TOKEN)
        self.put("nested/.git", PERSON)
        self.put(".github/note.md", PERSON)
        self.put(".gitkeep", TOKEN)
        r = self.report()
        self.assertEqual(r["git_entries_excluded"], 2)
        self.assertEqual(r["files_scanned"], 2)
        self.assertEqual(len(r["findings"]), 2)

    def test_filenames_and_directory_names_are_scanned(self):
        self.put("docs/" + PERSON + "/safe.txt", "safe")
        self.put(TOKEN + ".txt", "safe")
        self.assertEqual(self.rules(self.report()), {"filename.email", "secret.github-token"})

    def test_stdout_and_stderr_do_not_leak_content_or_filenames(self):
        name = PERSON + "-" + TOKEN + ".md"
        self.put(name, PERSON + "\n" + TOKEN + "\n" + HOME)
        p = self.cli()
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stderr, "")
        for private in (name, PERSON, TOKEN, HOME, str(self.root)):
            self.assertNotIn(private, p.stdout + p.stderr)
        r = json.loads(p.stdout)
        self.assertTrue(all(len(f["file_id"]) == 64 for f in r["findings"]))

    def test_cli_invalid_arguments_do_not_leak(self):
        p = self.cli("--unknown", TOKEN)
        self.assertEqual(p.returncode, 2)
        self.assertNotIn(TOKEN, p.stdout + p.stderr)
        self.assertEqual(p.stderr, "")

    def test_missing_root_or_allowlist_fails_closed(self):
        self.assertEqual(self.report()["status"], "incomplete")
        self.assertEqual(gate.scan(self.root / "missing")["status"], "incomplete")
        p = self.cli("--allowlist", str(self.root / PERSON))
        self.assertEqual(p.returncode, 2)
        self.assertNotIn(PERSON, p.stdout + p.stderr)

    def test_third_party_and_license_exact_allowances(self):
        for kind in ("third-party-contact", "license"):
            with self.subTest(kind=kind):
                self.put("README.md", CONTACT)
                allow = self.load([self.allowance(kind=kind)])
                r = self.report(allow=allow)
                self.assertEqual(r["status"], "clean")
                self.assertEqual(r["allowances_used"], 1)

    def test_allowance_does_not_cover_other_file_value_or_extra_occurrence(self):
        self.put("README.md", CONTACT + "\n" + CONTACT + "\n" + PERSON)
        self.put("other.md", CONTACT)
        r = self.report(allow=self.load([self.allowance()]))
        self.assertEqual(r["allowances_used"], 1)
        self.assertEqual(len(r["findings"]), 3)

    def test_unused_allowance_fails_closed(self):
        self.assertIn("unused-allowance", {e["code"] for e in self.report(allow=self.load([self.allowance()]))["errors"]})

    def test_invalid_expired_broad_duplicate_and_secret_allowances(self):
        bad_entries = [self.allowance(path="*.md"), self.allowance(path="../outside.md"), self.allowance(path="/outside.md"), self.allowance(path=".git/config"), self.allowance(expires="2000-01-01"), self.allowance(match_sha256="x"), self.allowance(max_count=True), self.allowance(rule="secret.github-token"), self.allowance(kind="owner-contact"), self.allowance(rule="markdown.user-home", kind="license"), self.allowance(location="path"), {**self.allowance(), "ignore_all": True}]
        for entry in bad_entries:
            with self.subTest(entry=list(entry)):
                with self.assertRaises(gate.PolicyError):
                    self.load([entry])
        with self.assertRaises(gate.PolicyError):
            self.load([self.allowance(), self.allowance()])

    def test_allowlist_malformed_error_is_redacted(self):
        path = self.put("allowlist.json", "{" + TOKEN)
        p = self.cli("--allowlist", str(path))
        self.assertEqual(p.returncode, 2)
        self.assertNotIn(TOKEN, p.stdout + p.stderr)
        path.write_text('{"version": 1, "allow": [], "allow": []}')
        with self.assertRaises(gate.PolicyError):
            gate.load_allowlist(path)

    def test_symlinks_not_followed_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as outside:
            (Path(outside) / "secret.md").write_text(PERSON)
            (self.root / "linked-dir").symlink_to(outside, target_is_directory=True)
            (self.root / "linked.md").symlink_to(Path(outside) / "secret.md")
            r = self.report()
            self.assertEqual(r["status"], "incomplete")
            self.assertEqual(r["files_scanned"], 0)
            self.assertEqual(len(r["errors"]), 2)
            self.assertEqual(r["findings"], [])

    def test_symlink_root_and_allowlist_fail_closed(self):
        actual = self.put("allowlist.json", '{"version": 1, "allow": []}')
        link = self.root / "link.json"
        link.symlink_to(actual)
        with self.assertRaises(gate.PolicyError):
            gate.load_allowlist(link)
        with tempfile.TemporaryDirectory() as outside:
            rootlink = Path(outside) / "root"
            rootlink.symlink_to(self.root, target_is_directory=True)
            self.assertEqual(gate.scan(rootlink)["status"], "incomplete")

    def test_file_total_and_count_limits_fail_closed(self):
        self.put("first.txt", "x" * 20)
        self.put("second.txt", "x" * 20)
        for kwargs, code in [({"max_file_bytes": 10}, "file-size-limit"), ({"max_total_bytes": 30}, "total-size-limit"), ({"max_files": 1}, "file-count-limit"), ({"max_files": 0}, "invalid-limit")]:
            with self.subTest(code=code):
                r = self.report(**kwargs)
                self.assertEqual(r["status"], "incomplete")
                self.assertIn(code, {e["code"] for e in r["errors"]})

    def test_binary_ascii_secrets_still_found(self):
        self.put("image.bin", b"\xff\x00" + TOKEN.encode() + b"\x00")
        r = self.report()
        self.assertEqual(self.rules(r), {"secret.github-token"})
        self.assertEqual(r["status"], "incomplete")

    def test_utf16_or_invalid_markdown_is_not_silent_clean(self):
        self.put("README.md", PERSON.encode("utf-16"))
        self.assertEqual(self.report()["status"], "incomplete")
        self.put("README.md", b"\x00" + PERSON.encode())
        self.assertEqual(self.report()["status"], "incomplete")

    def test_special_files_fail_without_blocking(self):
        os.mkfifo(self.root / "fifo")
        self.assertEqual(self.report()["errors"][0]["code"], "special-file-not-scanned")

    def test_read_error_never_becomes_clean(self):
        self.put("README.md", "safe")
        with mock.patch.object(gate.os, "open", side_effect=PermissionError(PERSON)):
            r = self.report()
        self.assertEqual(r["status"], "incomplete")
        self.assertNotIn(PERSON, json.dumps(r))

    def test_clean_exit_zero_and_location_accuracy(self):
        self.put("README.md", "safe\n")
        self.assertEqual(self.cli().returncode, 0)
        self.put("README.md", "heading\nxx " + PERSON)
        f = self.report()["findings"][0]
        self.assertEqual((f["line"], f["column"]), (2, 4))

    def test_long_nonmatching_text_smoke(self):
        self.put("large.txt", "a" * 100000)
        self.assertEqual(self.cli().returncode, 0)

    def test_fifo_allowlist_fails_without_hanging(self):
        self.put("README.md", "safe")
        fifo = self.root / "policy-fifo"
        os.mkfifo(fifo)
        p = subprocess.run([sys.executable, "-B", "-I", str(SCRIPT), "--root", str(self.root), "--allowlist", str(fifo)], capture_output=True, text=True, timeout=2, check=False)
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stderr, "")
        self.assertEqual(json.loads(p.stdout)["errors"][0]["code"], "invalid-allowlist")

    def test_root_and_policy_symlink_ancestors_rejected(self):
        self.put("actual/child/README.md", PERSON)
        policy = self.put("actual/policy.json", '{"version": 1, "allow": []}')
        (self.root / "linked").symlink_to(self.root / "actual", target_is_directory=True)
        for root in (self.root / "linked/child", self.root / "linked/child/.."):
            r = gate.scan(root)
            self.assertEqual(r["status"], "incomplete")
            self.assertEqual(r["files_scanned"], 0)
            self.assertEqual(r["findings"], [])
        with self.assertRaises(gate.PolicyError):
            gate.load_allowlist(self.root / "linked/policy.json")

    def test_punctuation_email_dos_regression(self):
        self.put("note.md", "!" * 1000000)
        p = subprocess.run([sys.executable, "-B", "-I", str(SCRIPT), "--root", str(self.root)], capture_output=True, text=True, timeout=3, check=False)
        self.assertEqual(p.returncode, 0)

    def test_dense_contacts_linear_location_and_bounded_default_output(self):
        self.put("note.md", (PERSON + "\n") * 50000)
        # This subprocess explicitly raises the API cap to exercise all 50,000
        # locations; passing solely by truncating output would not fix the bug.
        code = "import importlib.util,json,pathlib,sys; s=importlib.util.spec_from_file_location('gate',sys.argv[1]); m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m);r=m.scan(pathlib.Path(sys.argv[2]),max_findings=60000);print(json.dumps({'status':r['status'],'count':len(r['findings']),'last_line':r['findings'][-1]['line'],'last_column':r['findings'][-1]['column']}))"
        p = subprocess.run([sys.executable, "-B", "-I", "-c", code, str(SCRIPT), str(self.root)], capture_output=True, text=True, timeout=3, check=False)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(json.loads(p.stdout), {"status": "findings", "count": 50000, "last_line": 50000, "last_column": 1})
        r = self.report(max_findings=3)
        self.assertEqual(r["status"], "incomplete")
        self.assertEqual(len(r["findings"]), 3)
        self.assertIn("finding-count-limit", {e["code"] for e in r["errors"]})

    def test_credential_assignment_in_filename_and_directory(self):
        assignment = "api" + "_key=" + GENERIC
        self.put(assignment + ".txt", assignment)
        self.put(assignment + "/safe.txt", "safe")
        r = self.report()
        self.assertEqual(r["status"], "findings")
        self.assertEqual(self.rules(r), {"secret.credential-assignment"})
        self.assertIn("path", {f["location"] for f in r["findings"]})
        self.assertIn("content", {f["location"] for f in r["findings"]})

    def test_directory_and_depth_limits_fail_closed(self):
        self.put("one/two/three/README.md", "safe")
        for kwargs in ({"max_directories": 2}, {"max_depth": 1}):
            r = self.report(**kwargs)
            self.assertEqual(r["status"], "incomplete")
            self.assertIn("directory-count-or-depth-limit", {e["code"] for e in r["errors"]})

    def test_allowlist_future_expiry_and_size_are_bounded(self):
        with self.assertRaises(gate.PolicyError):
            self.load([self.allowance(expires="9999-12-31")])
        oversized = self.put("large-policy.json", " " * (128 * 1024 + 1))
        with self.assertRaises(gate.PolicyError):
            gate.load_allowlist(oversized)

    def test_email_ascii_length_scope_and_punctuation(self):
        valid = "a" * 64 + "@" + "example.org"
        overlong = "a" * 65 + "@" + "example.org"
        long_label = "name" + "@" + "a" * 64 + ".org"
        self.put("README.md", valid + ".\n" + overlong + "\n" + long_label)
        r = self.report()
        self.assertEqual(len(r["findings"]), 1)
        self.assertEqual(r["findings"][0]["line"], 1)

    def test_open_descriptors_released_on_success_and_error(self):
        # Linux-only test matches the declared execution platform.
        self.put("a/b/README.md", "safe")
        before = len(os.listdir("/proc/self/fd"))
        for _ in range(10):
            self.assertEqual(self.report()["status"], "clean")
            self.assertEqual(gate.scan(self.root / "missing")["status"], "incomplete")
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)

    def test_filename_email_survives_long_directory_prefix(self):
        self.put("a" * 70 + "/" + PERSON + ".txt", "safe")
        self.put("b" * 70 + "/" + PERSON + "/safe.txt", "safe")
        r = self.report()
        self.assertEqual(r["status"], "findings")
        self.assertEqual(self.rules(r), {"filename.email"})
        self.assertEqual(len(r["findings"]), 3)

    def test_global_enumeration_budget_bounds_nested_queues(self):
        for directory in ("a", "b"):
            for i in range(4):
                self.put(f"{directory}/file{i}.txt", "safe")
        r = self.report(max_files=4, max_directories=4)
        self.assertEqual(r["status"], "incomplete")
        self.assertIn("directory-entry-limit", {e["code"] for e in r["errors"]})


if __name__ == "__main__":
    unittest.main()
