import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "restore_pconline_cache.py"


def load_restore_module():
    spec = importlib.util.spec_from_file_location("restore_pconline_cache_tests", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def artifact(artifact_id, created_at, *, expired=False, branch="main", run_id=1):
    return {
        "id": artifact_id,
        "name": f"pconline-phone-data-early-{run_id}-1",
        "created_at": created_at,
        "expired": expired,
        "workflow_run": {
            "id": run_id,
            "head_branch": branch,
        },
    }


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, value in files.items():
            if not isinstance(value, bytes):
                value = json.dumps(value, ensure_ascii=False).encode("utf-8")
            bundle.writestr(name, value)
    return buffer.getvalue()


def valid_phone(phone_id):
    return {
        "phone_id": str(phone_id),
        "型号": f"有效手机 {phone_id}",
        "品牌": "苹果",
        "上市时间": "2026年7月",
        "处理器": "测试处理器",
        "屏幕": "6.1英寸",
        "电池": "4000mAh",
        "source": "太平洋电脑网",
        "url": f"https://product.pconline.com.cn/mobile/apple/{phone_id}.html",
    }


class PconlineCacheRestoreTests(unittest.TestCase):
    def test_cross_host_artifact_redirect_drops_github_authorization(self):
        restore = load_restore_module()
        request = urllib.request.Request(
            "https://api.github.com/repos/o/r/actions/artifacts/1/zip",
            headers={"Authorization": "Bearer secret"},
        )

        redirected = restore.SafeRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://artifactblob.example/archive.zip",
        )

        self.assertIsNone(redirected.get_header("Authorization"))

    def test_selects_latest_semantically_valid_raw_without_touching_progress(self):
        restore = load_restore_module()
        artifacts = [
            artifact(3, "2026-07-28T00:00:00Z", run_id=30),
            artifact(1, "2026-07-30T00:00:00Z", run_id=10),
            artifact(2, "2026-07-29T00:00:00Z", run_id=20),
        ]
        archives = {
            1: archive({"progress.json": {"current_page": 99}}),
            2: b"not a zip",
            3: archive(
                {
                    "progress.json": {"current_page": 88},
                    "json/123.json": valid_phone("123"),
                }
            ),
        }
        downloaded = []

        def download(candidate):
            downloaded.append(candidate["id"])
            return archives[candidate["id"]]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            progress = root / "progress.json"
            progress.write_text('{"current_page": 1}\n', encoding="utf-8")
            before = hashlib.sha256(progress.read_bytes()).hexdigest()

            result = restore.restore_latest_cache(
                artifacts, download, root / "json", branch="main"
            )

            after = hashlib.sha256(progress.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertEqual(
                json.loads((root / "json" / "123.json").read_text()),
                valid_phone("123"),
            )

        self.assertEqual(downloaded, [1, 2, 3])
        self.assertEqual(result["artifact_id"], 3)
        self.assertEqual(result["raw_count"], 1)

    def test_rejects_id_only_raw_and_uses_older_publishable_cache(self):
        restore = load_restore_module()
        artifacts = [
            artifact(2, "2026-07-30T00:00:00Z", run_id=20),
            artifact(1, "2026-07-29T00:00:00Z", run_id=10),
        ]
        archives = {
            2: archive({"json/456.json": {"phone_id": "456"}}),
            1: archive({"json/123.json": valid_phone("123")}),
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = restore.restore_latest_cache(
                artifacts,
                lambda candidate: archives[candidate["id"]],
                root / "json",
                branch="main",
            )
            self.assertEqual(result["artifact_id"], 1)
            self.assertFalse((root / "json" / "456.json").exists())
            self.assertTrue((root / "json" / "123.json").is_file())

    def test_rejects_identity_and_year_only_raw(self):
        restore = load_restore_module()
        artifacts = [
            artifact(2, "2026-07-30T00:00:00Z", run_id=20),
            artifact(1, "2026-07-29T00:00:00Z", run_id=10),
        ]
        archives = {
            2: archive(
                {
                    "json/456.json": {
                        "phone_id": "456",
                        "name": "残缺手机",
                        "上市时间": "2026年",
                    }
                }
            ),
            1: archive({"json/123.json": valid_phone("123")}),
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = restore.restore_latest_cache(
                artifacts,
                lambda candidate: archives[candidate["id"]],
                root / "json",
                branch="main",
            )

            self.assertEqual(result["artifact_id"], 1)
            self.assertFalse((root / "json" / "456.json").exists())

    def test_rejects_expired_wrong_branch_and_current_run(self):
        restore = load_restore_module()
        artifacts = [
            artifact(1, "2026-07-30T00:00:00Z", expired=True, run_id=10),
            artifact(2, "2026-07-29T00:00:00Z", branch="feature", run_id=20),
            artifact(3, "2026-07-28T00:00:00Z", run_id=30),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            result = restore.restore_latest_cache(
                artifacts,
                lambda _candidate: archive({"json/123.json": valid_phone("123")}),
                Path(tmp) / "json",
                branch="main",
                exclude_run_id=30,
            )

        self.assertIsNone(result)

    def test_traversal_rejects_entire_newer_artifact_before_writing(self):
        restore = load_restore_module()
        artifacts = [
            artifact(2, "2026-07-30T00:00:00Z", run_id=20),
            artifact(1, "2026-07-29T00:00:00Z", run_id=10),
        ]
        archives = {
            2: archive(
                {
                    "json/456.json": valid_phone("456"),
                    "../escape.json": b"not allowed",
                }
            ),
            1: archive({"json/123.json": valid_phone("123")}),
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = restore.restore_latest_cache(
                artifacts,
                lambda candidate: archives[candidate["id"]],
                root / "json",
                branch="main",
            )

            self.assertEqual(result["artifact_id"], 1)
            self.assertFalse((root / "json" / "456.json").exists())
            self.assertTrue((root / "json" / "123.json").is_file())
            self.assertFalse((root / "escape.json").exists())

    def test_successful_restore_replaces_destination_without_stale_files(self):
        restore = load_restore_module()
        artifacts = [artifact(1, "2026-07-30T00:00:00Z")]

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "json"
            destination.mkdir()
            (destination / "stale.json").write_text("{}", encoding="utf-8")

            restore.restore_latest_cache(
                artifacts,
                lambda _candidate: archive({"json/123.json": valid_phone("123")}),
                destination,
                branch="main",
            )

            self.assertFalse((destination / "stale.json").exists())
            self.assertTrue((destination / "123.json").is_file())

    def test_staging_write_failure_leaves_existing_destination_untouched(self):
        restore = load_restore_module()
        artifacts = [artifact(1, "2026-07-30T00:00:00Z")]

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "json"
            destination.mkdir()
            old = destination / "old.json"
            old.write_text('{"old": true}', encoding="utf-8")

            with mock.patch.object(
                Path, "write_bytes", side_effect=OSError("disk full")
            ):
                with self.assertRaises(OSError):
                    restore.restore_latest_cache(
                        artifacts,
                        lambda _candidate: archive(
                            {"json/123.json": valid_phone("123")}
                        ),
                        destination,
                        branch="main",
                    )

            self.assertEqual(old.read_text(encoding="utf-8"), '{"old": true}')
            self.assertEqual([path.name for path in destination.iterdir()], ["old.json"])

    def test_download_transport_failure_is_not_treated_as_invalid_cache(self):
        restore = load_restore_module()
        artifacts = [
            artifact(2, "2026-07-30T00:00:00Z", run_id=20),
            artifact(1, "2026-07-29T00:00:00Z", run_id=10),
        ]

        def download(candidate):
            if candidate["id"] == 2:
                raise urllib.error.URLError("temporary failure")
            return archive({"json/123.json": valid_phone("123")})

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(urllib.error.URLError):
                restore.restore_latest_cache(
                    artifacts, download, Path(tmp) / "json", branch="main"
                )

    def test_archive_resource_limits_reject_entire_candidate(self):
        restore = load_restore_module()
        too_many = {
            f"json/{phone_id}.json": valid_phone(phone_id)
            for phone_id in range(1, 5)
        }

        with mock.patch.object(restore, "MAX_ARCHIVE_MEMBERS", 3):
            with self.assertRaises(restore.InvalidCacheArtifact):
                restore._read_raw_files(archive(too_many))

    def test_workflow_restore_and_incomplete_run_safety_contract(self):
        text = (ROOT / ".github/workflows/crawl-pconline.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("actions: read", text)
        restore_at = text.index("- name: Restore latest PConline raw cache")
        crawl_at = text.index("- name: Run PConline crawler")
        self.assertLess(restore_at, crawl_at)
        restore_block = text[restore_at:crawl_at]
        self.assertIn("scripts/restore_pconline_cache.py", restore_block)
        self.assertIn("github.event.inputs.force_restart != 'true'", restore_block)
        self.assertIn("github.event.inputs.debug_mode != 'true'", restore_block)
        self.assertNotIn('git config user.name "github-actions[bot]"', text)
        self.assertEqual(text.count('git config user.name "Fatty911"'), 2)
        self.assertEqual(text.count('GIT_SYNC_BRANCH="$GITHUB_REF_NAME"'), 2)

        early_block = text.split(
            "- name: Upload crawl data (early, after step1)", 1
        )[1].split("- name: Commit incomplete crawl progress", 1)[0]
        self.assertNotIn("continue-on-error: true", early_block)
        self.assertIn("always()", early_block)
        self.assertIn("id: early_cache", early_block)
        self.assertIn("retention-days: 30", early_block)
        self.assertIn("if-no-files-found: error", early_block)

        step1_block = text.split("- name: Run PConline crawler", 1)[1].split(
            "- name: Upload crawl data (early, after step1)", 1
        )[0]
        self.assertNotIn("git_sync_progress.sh", step1_block)
        commit_incomplete_at = text.index("- name: Commit incomplete crawl progress")
        early_upload_at = text.index("- name: Upload crawl data (early, after step1)")
        self.assertLess(early_upload_at, commit_incomplete_at)
        incomplete_block = text[commit_incomplete_at:].split(
            "- name: Parse and merge data", 1
        )[0]
        self.assertIn("steps.early_cache.outcome == 'success'", incomplete_block)

        mark_block = text.split("- name: Mark crawl complete and commit", 1)[1].split(
            "- name: Upload crawl data", 1
        )[0]
        self.assertEqual(mark_block.count('touch "$PCONLINE_DONE_MARKER"'), 1)
        self.assertNotIn("steps.validate_data.outputs.has_data", mark_block)

        for step_name in (
            "Parse and merge data",
            "Validate generated PConline data",
            "Generate summary",
            "Upload crawl data",
            "检测新增数据并触发合并分析",
        ):
            workflow = yaml.safe_load(text)
            steps = workflow["jobs"]["pconline-crawl"]["steps"]
            step = next(item for item in steps if item.get("name") == step_name)
            self.assertIn(
                "steps.step1.outputs.complete == 'true'", str(step.get("if", ""))
            )

        dispatch_block = text.split("- name: 触发合并分析工作流", 1)[1]
        self.assertIn("steps.step1.outputs.complete == 'true'", dispatch_block)

    def test_git_sync_recognizes_repository_progress_paths(self):
        text = (ROOT / "scripts/git_sync_progress.sh").read_text(encoding="utf-8")

        self.assertIn(
            "crawl_state/zol/progress.json|crawl_state/pconline/progress.json",
            text,
        )


if __name__ == "__main__":
    unittest.main()
