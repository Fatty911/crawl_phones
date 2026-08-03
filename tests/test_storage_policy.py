from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from scripts.validate_storage_policy import stages_data_directory


ROOT = Path(__file__).resolve().parents[1]


class StoragePolicyTests(unittest.TestCase):
    def test_current_storage_policy_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/validate_storage_policy.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_dynamic_broad_and_runtime_data_staging_fails_closed(self) -> None:
        for command in (
            "git add -A",
            "git add --all",
            "git add .",
            "git add data/latest.json",
            "git add -- $(git diff --name-only)",
            "git add -- `git diff --name-only`",
        ):
            with self.subTest(command=command):
                self.assertTrue(stages_data_directory(command))

    def test_fixed_repair_allowlist_is_safe(self) -> None:
        self.assertFalse(
            stages_data_directory(
                "git add -- scripts/merge_phones.py scripts/crawl_zol.py "
                "scripts/crawl_pconline.py scripts/crawl_cnmo.py"
            )
        )


if __name__ == "__main__":
    unittest.main()
