import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    original_argv = sys.argv
    try:
        sys.argv = [str(path)]
        spec.loader.exec_module(module)
    finally:
        sys.argv = original_argv
    return module


merge = load_module("merge_phones_priority_tests", SCRIPTS / "merge_phones.py")
preserve = load_module("preserve_publish_baseline_priority_tests", SCRIPTS / "preserve_publish_baseline.py")
zol = load_module("crawl_zol_priority_tests", SCRIPTS / "crawl_zol.py")


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
        self.encoding = None


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return self.response


class PhonePriorityAndDedupTests(unittest.TestCase):
    def test_pages_side_conditions_exclude_all_core_condition_ids(self):
        config = json.loads((ROOT / "docs/phones/filter_conditions.json").read_text(encoding="utf-8"))
        all_ids = {item["id"] for item in config["conditions"]}
        core_ids = {item for group in config["centerConditionGroups"] for item in group["conditionIds"]}
        self.assertEqual(all_ids, core_ids)
        html = (ROOT / "docs/phones/index.html").read_text(encoding="utf-8")
        app = (ROOT / "docs/phones/app.js").read_text(encoding="utf-8")
        self.assertIn('id="advancedConditionSection" hidden', html)
        self.assertIn("<h2>更多条件</h2>", html)
        self.assertIn("function sideConditions()", app)
        self.assertIn("els.advancedConditionSection.hidden = conditions.length === 0", app)

    def test_zol_uses_ordered_phone_ranking_and_preserves_first_rank(self):
        html = "".join([
            '<a href="//detail.zol.com.cn/cell_phone/index22.shtml">B</a>',
            '<a href="//detail.zol.com.cn/cell_phone/index11.shtml">A</a>',
            '<a href="//detail.zol.com.cn/cell_phone/index22.shtml">B duplicate</a>',
        ])
        session = FakeSession(FakeResponse(html))
        with mock.patch.object(zol, "human_delay", return_value=None):
            ranks = zol._crawl_hot_list(session)
        self.assertEqual(session.urls, ["https://top.zol.com.cn/compositor/57/cell_phone.html"])
        self.assertEqual(ranks, {"22": 0, "11": 1})
        source = (SCRIPTS / "crawl_zol.py").read_text(encoding="utf-8")
        self.assertNotIn("_count_local_brands", source)
        self.assertNotIn("本地品牌热度", source)

    def test_zol_rank_sort_preserves_unranked_source_order_and_failure_order(self):
        phones = [{"id": "1"}, {"id": "2"}, {"id": "3"}, {"id": "4"}]
        self.assertEqual([p["id"] for p in zol._prioritize_hot_models(phones, {"3": 0, "1": 1})], ["3", "1", "2", "4"])
        self.assertEqual(zol._prioritize_hot_models(phones, {}), phones)

    def test_pconline_uses_dynamic_directory_order_and_source_hot_order(self):
        source = (SCRIPTS / "crawl_pconline.py").read_text(encoding="utf-8")
        self.assertNotIn("PHONE_BRAND_HEAT_ORDER", source)
        self.assertNotIn("crawl_brand_heat", source)
        self.assertNotIn("sort_brands_by_heat", source)
        self.assertIn("品牌按实时目录顺序扫描", source)
        self.assertIn("品牌内型号保持源站默认最热门顺序", source)
        self.assertIn("/{offset}s1.shtml", source)

    def test_cnmo_does_not_claim_unverified_heat_or_sales(self):
        source = (SCRIPTS / "crawl_cnmo.py").read_text(encoding="utf-8")
        self.assertIn("源站列表顺序，未验证为热度或销量", source)

    def test_storage_signature_only_uses_concrete_model_variant(self):
        self.assertEqual(merge.model_storage_signature({"型号": "荣耀X70(8GB+128GB)"}), (8, 128))
        self.assertEqual(merge.model_storage_signature({"型号": "苹果iPhone 16 Pro(256GB)"}), (256,))
        self.assertEqual(merge.model_storage_signature({"型号": "荣耀X70", "内存": "8GB|12GB", "存储": "128GB|256GB|512GB"}), ())
        self.assertEqual(merge.model_storage_signature({"型号": "苹果iPhone 17 Pro Max", "内存": "LPDDR5X", "存储": "256GB|512GB|1TB"}), ())
        aggregate = {"型号": "荣耀Magic3", "内存": "8GB", "存储": "128GB|256GB"}
        self.assertEqual(merge.model_storage_signature(aggregate), ())
        self.assertEqual(merge.model_storage_signatures(aggregate), {(8, 128), (8, 256)})

    def test_baseline_prefers_multisource_row_covering_single_primary_id(self):
        single = {"手机ID": "cnmo-1", "型号": "示例机(8GB+128GB)", "数据来源": "CNMO", "验证状态": "单源"}
        multi = {"手机ID": "zol-1", "关联手机ID": "cnmo-1|zol-1", "型号": "示例机(8GB/128GB)", "数据来源": "中关村在线+CNMO", "验证状态": "双源差异"}
        merged, restored = preserve.preserve_baseline([single, multi], [])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["手机ID"], "zol-1")
        self.assertEqual(restored, ["id:zol-1"])
        preserve.verify_superset([single, multi], merged)

    def test_baseline_keeps_unique_single_and_candidate_coverage(self):
        unique = {"手机ID": "unique-1", "型号": "独有机", "数据来源": "CNMO", "验证状态": "单源"}
        merged, _ = preserve.preserve_baseline([unique], [])
        self.assertEqual([row["手机ID"] for row in merged], ["unique-1"])
        candidate = {"手机ID": "zol-2", "关联手机ID": "unique-1|zol-2", "型号": "独有机", "数据来源": "中关村在线+CNMO", "验证状态": "双源差异"}
        merged, restored = preserve.preserve_baseline([unique], [candidate])
        self.assertEqual(merged, [candidate])
        self.assertEqual(restored, [])
        preserve.verify_superset([unique], merged)


if __name__ == "__main__":
    unittest.main()
