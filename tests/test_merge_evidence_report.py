import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/merge_evidence_report.py"


class MergeEvidenceReportTests(unittest.TestCase):
    def test_report_counts_sources_statuses_and_optional_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_a = root / "zol.json"
            raw_b = root / "cnmo.json"
            merged = root / "merged.json"
            diff = root / "diff.csv"
            output = root / "report.json"
            raw_a.write_text(
                json.dumps(
                    [
                        {"型号": "A", "数据来源": "中关村在线", "验证状态": "双源一致"},
                        {"型号": "B", "数据来源": "ZOL", "验证状态": "单源"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            raw_b.write_text(
                json.dumps(
                    [{"型号": "C", "atomic_source_names": ["CNMO"], "publish_eligible": True}],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            merged.write_text(
                json.dumps(
                    [
                        {"型号": "A", "atomic_source_names": ["ZOL", "PConline"], "验证状态": "双源一致"},
                        {"型号": "C", "atomic_source_names": ["CNMO"], "验证状态": "单源"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            diff.write_text("手机,配置项\nA,价格\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--raw",
                    str(raw_a),
                    str(raw_b),
                    "--merged",
                    str(merged),
                    "--diff",
                    str(diff),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["published_count"], 2)
            self.assertEqual(report["multi_source_count"], 1)
            self.assertEqual(report["diff_row_count"], 1)
            self.assertEqual(report["source_combinations"]["PConline+ZOL"], 1)
            self.assertEqual(report["validation_status_counts"]["双源一致"], 1)
            self.assertEqual(len(report["raw"]), 2)

    def test_missing_raw_input_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            merged = root / "merged.json"
            merged.write_text("[]", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--raw",
                    str(root / "missing-*.json"),
                    "--merged",
                    str(merged),
                    "--output",
                    str(root / "report.json"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
