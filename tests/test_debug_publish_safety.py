from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = ROOT / "scripts" / "verify_publish_superset.py"


def load_verify_module():
    spec = importlib.util.spec_from_file_location("verify_publish_superset", VERIFY_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {VERIFY_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublishSupersetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verify = load_verify_module()

    def test_identity_prefers_phone_id_then_id_then_normalized_model(self) -> None:
        self.assertEqual("id:phone-1", self.verify.identity_key({"手机ID": " phone-1 ", "id": "ignored"}))
        self.assertEqual("id:fallback-2", self.verify.identity_key({"id": " fallback-2 ", "型号": "ignored"}))
        self.assertEqual("model:小米 15 ultra", self.verify.identity_key({"型号": " 小米　15   Ultra "}))
        self.assertEqual("model:pixel 10 pro", self.verify.identity_key({"name": "Pixel 10  PRO"}))

    def test_candidate_must_preserve_rows_and_all_baseline_identities(self) -> None:
        baseline = [{"手机ID": "1"}, {"型号": "Model A"}]
        candidate = [{"手机ID": "1"}, {"型号": "Model A"}, {"id": "3"}]
        self.verify.verify_superset(baseline, candidate)

        with self.assertRaisesRegex(ValueError, "行数减少"):
            self.verify.verify_superset(baseline, candidate[:1])
        with self.assertRaisesRegex(ValueError, "缺少基线身份"):
            self.verify.verify_superset(baseline, [{"手机ID": "1"}, {"id": "3"}])

    def test_candidate_related_phone_ids_preserve_merged_source_identities(self) -> None:
        baseline = [{"手机ID": "1624724", "型号": "荣耀Magic3(8+128GB)"}]
        candidate = [
            {
                "手机ID": "1397100",
                "型号": "荣耀Magic3",
                "数据来源": "太平洋电脑网+CNMO",
                "关联手机ID": "1397100|1624724",
            }
        ]
        self.verify.verify_superset(baseline, candidate)

        with self.assertRaisesRegex(ValueError, "缺少基线身份"):
            self.verify.verify_superset(baseline, [{"手机ID": "1397100", "型号": "荣耀Magic3"}])

    def test_cli_rejects_invalid_or_non_list_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            baseline = tmp_path / "baseline.json"
            candidate = tmp_path / "candidate.json"
            baseline.write_text(json.dumps([{"id": "1"}]), encoding="utf-8")
            candidate.write_text("{}", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VERIFY_SCRIPT), str(baseline), str(candidate)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("JSON 顶层必须是数组", result.stderr)


class WorkflowSafetyContractTests(unittest.TestCase):
    def test_machine_readable_workflow_expectations(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/validate_workflow_expectations.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
