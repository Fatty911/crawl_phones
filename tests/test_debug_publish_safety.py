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
PRESERVE_SCRIPT = ROOT / "scripts" / "preserve_publish_baseline.py"


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

    def test_candidate_must_preserve_all_baseline_identities(self) -> None:
        baseline = [{"手机ID": "1"}, {"型号": "Model A"}]
        candidate = [{"手机ID": "1"}, {"型号": "Model A"}, {"id": "3"}]
        self.verify.verify_superset(baseline, candidate)

        with self.assertRaisesRegex(ValueError, "缺少基线身份"):
            self.verify.verify_superset(baseline, candidate[:1])
        with self.assertRaisesRegex(ValueError, "缺少基线身份"):
            self.verify.verify_superset(baseline, [{"手机ID": "1"}, {"id": "3"}])

    def test_related_ids_allow_traceable_row_consolidation(self) -> None:
        baseline = [{"手机ID": "1"}, {"手机ID": "2"}]
        candidate = [{"手机ID": "1", "关联手机ID": "1|2"}]

        self.verify.verify_superset(baseline, candidate)

        with self.assertRaisesRegex(ValueError, "缺少基线身份"):
            self.verify.verify_superset(baseline, [{"手机ID": "1"}])

    def test_candidate_must_keep_baseline_related_id_history(self) -> None:
        baseline = [{"手机ID": "1", "关联手机ID": "1|2"}]

        self.verify.verify_superset(baseline, [{"手机ID": "1", "关联手机ID": "2"}])
        with self.assertRaisesRegex(ValueError, "缺少基线身份"):
            self.verify.verify_superset(baseline, [{"手机ID": "1"}])

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

    def test_out_of_scope_cnmo_single_source_baseline_is_not_required(self) -> None:
        baseline = [
            {"手机ID": "pixel-cnmo", "型号": "谷歌Pixel 8 Pro", "品牌": "谷歌", "数据来源": "CNMO"},
            {"手机ID": "hinova-cnmo", "型号": "Hi nova 10 Pro(8+256GB)", "品牌": "", "数据来源": "CNMO"},
            {"手机ID": "honor-cnmo", "型号": "荣耀X80i(8GB+256GB)", "品牌": "荣耀", "数据来源": "CNMO"},
        ]
        candidate = [
            {"手机ID": "hinova-cnmo", "型号": "Hi nova 10 Pro(8+256GB)", "品牌": "", "数据来源": "CNMO"},
            {"手机ID": "honor-cnmo", "型号": "荣耀X80i(8GB+256GB)", "品牌": "荣耀", "数据来源": "CNMO"},
        ]

        self.verify.verify_superset(baseline, candidate)

        with self.assertRaisesRegex(ValueError, "缺少基线身份"):
            self.verify.verify_superset(baseline, [{"手机ID": "other", "型号": "其它"}])

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


class PreservePublishBaselineTests(unittest.TestCase):
    def test_cli_restores_missing_identity_in_json_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            baseline = tmp_path / "baseline.json"
            candidate = tmp_path / "candidate.json"
            candidate_csv = tmp_path / "candidate.csv"
            baseline.write_text(
                json.dumps([{"手机ID": "1"}, {"手机ID": "2", "型号": "Model 2"}]),
                encoding="utf-8",
            )
            candidate.write_text(json.dumps([{"手机ID": "1"}]), encoding="utf-8")
            candidate_csv.write_text("手机ID\n1\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(PRESERVE_SCRIPT), str(baseline), str(candidate), str(candidate_csv)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )

            restored = json.loads(candidate.read_text(encoding="utf-8"))
            csv_text = candidate_csv.read_text(encoding="utf-8-sig")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(["1", "2"], [row["手机ID"] for row in restored])
        self.assertIn("Model 2", csv_text)
        self.assertIn("restored=1", result.stdout)

    def test_cli_cleans_marketing_copy_from_restored_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            baseline = tmp_path / "baseline.json"
            candidate = tmp_path / "candidate.json"
            candidate_csv = tmp_path / "candidate.csv"
            baseline.write_text(
                json.dumps(
                    [
                        {
                            "手机ID": "2",
                            "型号": "Model 2",
                            "内存": "16GB>游戏运行一般>LPDDR5X Ultra",
                            "存储": "256GB>5461首歌曲>UFS 4.0",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            candidate.write_text(json.dumps([{"手机ID": "1"}]), encoding="utf-8")
            candidate_csv.write_text("手机ID\n1\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(PRESERVE_SCRIPT), str(baseline), str(candidate), str(candidate_csv)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
            restored = json.loads(candidate.read_text(encoding="utf-8"))
            csv_text = candidate_csv.read_text(encoding="utf-8-sig")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("16GB|LPDDR5X Ultra", restored[1]["内存"])
        self.assertEqual("256GB|UFS 4.0", restored[1]["存储"])
        self.assertNotRegex(csv_text, r"游戏运行|首歌曲")


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
