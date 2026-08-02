from __future__ import annotations

import unittest

from scripts.single_source_repair import (
    ALLOWED_FILES,
    RepairInputError,
    _json_response,
    _strict_json_load,
    analyze_payload,
    validate_patch_text,
)


class SingleSourceRepairTests(unittest.TestCase):
    def test_phone_payload_uses_chinese_source_field(self) -> None:
        report = analyze_payload(
            [
                {"手机ID": "1", "品牌": "A", "型号": "M", "数据来源": "中关村在线+CNMO"},
                {"手机ID": "2", "品牌": "B", "型号": "N", "数据来源": "中关村在线"},
            ],
            "phones",
        )
        self.assertEqual(report["schema"], "phones:list")
        self.assertEqual(report["multi_count"], 1)
        self.assertEqual(report["single_count"], 1)

    def test_car_payload_groups_series_and_reports_merge_gap(self) -> None:
        report = analyze_payload(
            {
                "data": [
                    {"车系ID": "10", "车系": "A", "车型名称": "M", "年款": "2025", "数据来源": "汽车之家+懂车帝"},
                    {"车系ID": "10", "车系": "A", "车型名称": "M", "年款": "2025", "数据来源": "汽车之家"},
                    {"车系ID": "20", "车系": "B", "车型名称": "N", "年款": "2025", "数据来源": "汽车之家"},
                ]
            },
            "cars",
        )
        self.assertEqual(report["schema"], "cars:data")
        self.assertEqual(report["causes"]["cross_source_merge_gap"], 1)
        self.assertEqual(report["causes"]["identity_only_single"], 1)

    def test_laptop_atomic_source_array_is_preferred(self) -> None:
        report = analyze_payload(
            {
                "items": [
                    {"brand": "A", "model": "M", "source": "JD", "atomic_source_names": ["JD", "ZOL"]},
                    {"brand": "B", "model": "N", "source": "JD", "atomic_source_names": ["JD"]},
                ]
            },
            "laptops",
        )
        self.assertEqual(report["schema"], "laptops:items")
        self.assertEqual(report["multi_count"], 1)
        self.assertEqual(report["source_fields"]["atomic_source_names"], 2)

    def test_invalid_or_missing_source_payload_is_noop_input(self) -> None:
        with self.assertRaises(RepairInputError):
            analyze_payload({"items": []}, "laptops")
        with self.assertRaises(RepairInputError):
            analyze_payload([{"品牌": "A", "型号": "M"}], "phones")
        with self.assertRaises(RepairInputError):
            analyze_payload([{"手机ID": "local-only", "数据来源": "ZOL"}], "phones")

    def test_source_suffix_and_nonstandard_json_are_rejected_or_normalized(self) -> None:
        report = analyze_payload(
            [{"车系": "A", "车型名称": "M", "年款": "2025", "数据来源": "懂车帝(车系级)"}],
            "cars",
        )
        self.assertEqual(report["available_sources"], ["懂车帝(车系级)"])
        with self.assertRaises(RepairInputError):
            _json_response('{"should_fix": true, "confidence": NaN}')
        with self.assertRaises(RepairInputError):
            _json_response('{"should_fix": true, "confidence": 1e309}')
        with self.assertRaises(RepairInputError):
            _json_response('{"should_fix": true, "confidence": 0.9, "confidence": 0.8}')
        with self.assertRaises(RepairInputError):
            _json_response('```json {"should_fix": false}```')

    def test_strict_input_and_identity_boundaries(self) -> None:
        with self.assertRaises(RepairInputError):
            _strict_json_load('{"value": 1e309}', "Pages payload")
        with self.assertRaises(RepairInputError):
            analyze_payload(
                [{"品牌": "A", "型号": "M", "数据来源": {"name": "ZOL"}}],
                "phones",
            )
        with self.assertRaises(RepairInputError):
            analyze_payload(
                {"items": [{"brand": "A", "model": "M", "identity_key": "!!!", "source": "ZOL"}]},
                "laptops",
            )

    def test_workflow_patch_is_rejected(self) -> None:
        patch = """diff --git a/.github/workflows/deploy-pages.yml b/.github/workflows/deploy-pages.yml
--- a/.github/workflows/deploy-pages.yml
+++ b/.github/workflows/deploy-pages.yml
@@ -1,1 +1,1 @@
-name: old
+name: new
"""
        with self.assertRaises(RepairInputError):
            validate_patch_text(patch, "phones")
        self.assertTrue(ALLOWED_FILES["phones"])


if __name__ == "__main__":
    unittest.main()
