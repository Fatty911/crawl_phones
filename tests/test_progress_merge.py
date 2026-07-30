import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "merge_progress_json.py"


def load_module():
    spec = importlib.util.spec_from_file_location("merge_progress_json_tests", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProgressMergeTests(unittest.TestCase):
    def test_pconline_cursor_bundle_uses_conservative_complete_source(self):
        merge = load_module()
        ours = {
            "current_brand_index": 2,
            "current_brand": "oppo",
            "current_page": 10,
            "brand_plan": ["huawei", "apple", "oppo", "honor"],
            "scan_complete": False,
            "previous_list_brand": "oppo",
            "previous_list_page": 9,
            "previous_list_ids": ["oppo-9"],
            "processed_phones": ["ours"],
        }
        theirs = {
            "current_brand_index": 3,
            "current_brand": "honor",
            "current_page": 1,
            "brand_plan": ["huawei", "apple", "oppo", "honor"],
            "scan_complete": False,
            "previous_list_brand": "oppo",
            "previous_list_page": 10,
            "previous_list_ids": ["oppo-10"],
            "processed_phones": ["theirs"],
        }

        result = merge.merge_progress({}, ours, theirs)

        self.assertEqual(
            (
                result["current_brand_index"],
                result["current_brand"],
                result["current_page"],
            ),
            (2, "oppo", 10),
        )
        self.assertEqual(result["previous_list_page"], 9)
        self.assertEqual(result["previous_list_ids"], ["oppo-9"])
        self.assertEqual(result["processed_phones"], ["ours", "theirs"])

    def test_incomparable_brand_plans_reset_to_safe_start(self):
        merge = load_module()
        ours = {
            "current_brand_index": 2,
            "current_brand": "oppo",
            "current_page": 8,
            "brand_plan": ["huawei", "apple", "oppo"],
            "scan_complete": False,
        }
        theirs = {
            "current_brand_index": 1,
            "current_brand": "honor",
            "current_page": 3,
            "brand_plan": ["huawei", "honor", "oppo"],
            "scan_complete": False,
        }

        result = merge.merge_progress({}, ours, theirs)

        self.assertEqual(result["current_brand_index"], 0)
        self.assertEqual(result["current_brand"], "")
        self.assertEqual(result["current_page"], 1)
        self.assertEqual(result["previous_list_ids"], [])

    def test_legacy_cursor_without_brand_plan_forces_safe_reset(self):
        merge = load_module()
        legacy = {
            "current_brand_index": 1,
            "current_page": 9,
            "processed_phones": ["legacy"],
        }
        current = {
            "current_brand_index": 2,
            "current_brand": "oppo",
            "current_page": 3,
            "brand_plan": ["huawei", "apple", "oppo"],
            "scan_complete": False,
            "processed_phones": ["current"],
        }

        result = merge.merge_progress({}, current, legacy)

        self.assertEqual(result["current_brand_index"], 0)
        self.assertEqual(result["current_brand"], "")
        self.assertEqual(result["current_page"], 1)
        self.assertEqual(result["previous_list_ids"], [])
        self.assertEqual(result["processed_phones"], ["current", "legacy"])


if __name__ == "__main__":
    unittest.main()
