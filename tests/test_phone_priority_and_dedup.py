import importlib.util
import json
import sys
import tempfile
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
pconline = load_module("crawl_pconline_priority_tests", SCRIPTS / "crawl_pconline.py")


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

    def test_pconline_uses_stable_idc_2026_q2_brand_groups(self):
        brands = [
            "samsung",
            "oneplus",
            "honor",
            "bubugao",
            "huawei",
            "realme",
            "apple",
            "oppo",
            "redmi",
            "iqoo",
            "vivo",
            "miui",
            "wiko",
            "lenovo",
            "zte",
            "unknown_b",
            "unknown_a",
        ]

        self.assertEqual(
            pconline.order_pconline_brands(brands),
            [
                "huawei",
                "apple",
                "oppo",
                "oneplus",
                "realme",
                "bubugao",
                "vivo",
                "iqoo",
                "miui",
                "redmi",
                "honor",
                "wiko",
                "lenovo",
                "zte",
                "samsung",
                "unknown_a",
                "unknown_b",
            ],
        )

    def test_pconline_catalog_selector_excludes_noise_and_deduplicates_ids(self):
        html = """
        <a href="//product.pconline.com.cn/mobile/oppo/999.html">推荐噪声</a>
        <ul id="JlistItems" class="list-items list-type-tw clearfix">
          <li><a class="item-title-name"
            href="//product.pconline.com.cn/mobile/oppo/101.html">首个标题</a></li>
          <li><a class="item-title-name"
            href="//product.pconline.com.cn/mobile/oppo/102.html">第二个标题</a></li>
          <li><a class="item-title-name"
            href="//product.pconline.com.cn/mobile/oppo/101.html">重复标题</a></li>
        </ul>
        """
        session = FakeSession(FakeResponse(html))

        with mock.patch.object(pconline, "human_delay", return_value=None):
            phones = pconline.crawl_list_page(session, "oppo", 1)

        self.assertEqual([phone["id"] for phone in phones], ["101", "102"])
        self.assertEqual(phones[0]["name"], "首个标题")

    def test_pconline_missing_catalog_is_retryable_failure(self):
        session = FakeSession(
            FakeResponse(
                '<a href="//product.pconline.com.cn/mobile/oppo/999.html">推荐噪声</a>'
            )
        )

        with mock.patch.object(pconline, "human_delay", return_value=None):
            with self.assertRaises(pconline.ListPageFetchError):
                pconline.crawl_list_page(session, "oppo", 1)

    def test_pconline_brand_directory_failure_is_retryable(self):
        session = FakeSession(FakeResponse("", status_code=503))

        with self.assertRaises(pconline.ListPageFetchError):
            pconline.crawl_brand_list(session)

    def test_pconline_brand_directory_failure_preserves_exact_cursor(self):
        test_progress = {
            "crawled_phones": [],
            "processed_phones": [],
            "skipped_phones": {},
            "total_phones": 0,
            "current_brand_index": 2,
            "current_brand": "oppo",
            "current_page": 2,
        }

        with tempfile.TemporaryDirectory() as tmp:
            progress_path = Path(tmp) / "progress.json"
            with mock.patch.object(pconline, "progress", test_progress):
                with mock.patch.object(pconline, "progress_file", str(progress_path)):
                    with mock.patch.object(pconline, "INCREMENTAL_MODE", True):
                        with mock.patch.object(pconline, "AUTO_MODE", True):
                            with mock.patch.object(
                                pconline,
                                "_scan_all_models",
                                side_effect=pconline.ListPageFetchError(
                                    "directory unavailable"
                                ),
                            ):
                                with mock.patch.object(
                                    pconline, "get_session", return_value=object()
                                ):
                                    with self.assertRaisesRegex(SystemExit, "10"):
                                        pconline.step1_crawl_list_and_detail()

        self.assertEqual(
            (
                test_progress["current_brand_index"],
                test_progress["current_brand"],
                test_progress["current_page"],
            ),
            (2, "oppo", 2),
        )

    def test_pconline_existing_ids_require_raw_or_verified_old_year(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            (raw_dir / "123.json").write_text(
                json.dumps(
                    {
                        "phone_id": "123",
                        "型号": "有效手机",
                        "品牌": "苹果",
                        "上市时间": "2026年7月",
                        "处理器": "测试处理器",
                        "屏幕": "6.1英寸",
                        "电池": "4000mAh",
                        "source": "太平洋电脑网",
                        "url": "https://product.pconline.com.cn/mobile/apple/123.html",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (raw_dir / "broken.json").write_text("{}", encoding="utf-8")
            test_progress = {
                "crawled_phones": ["missing-raw"],
                "processed_phones": ["processed-only"],
                "skipped_phones": {
                    "old-id": "year:2020",
                    "edge-id": "year:2021",
                    "retry-id": "no_release_year",
                },
            }

            with mock.patch.object(pconline, "pconline_json_dir", str(raw_dir)):
                with mock.patch.object(pconline, "progress", test_progress):
                    existing = pconline._get_existing_phone_ids()

        self.assertEqual(existing, {"123", "old-id"})

    def test_pconline_resume_rejects_previous_page_replayed_at_cursor(self):
        phones = [
            {
                "id": str(index),
                "name": f"手机 {index}",
                "brand": "oppo",
                "url": f"https://example.invalid/{index}",
                "source": "太平洋电脑网",
            }
            for index in range(25)
        ]
        calls = []

        def fake_page(_session, brand, page):
            calls.append((brand, page))
            return list(phones)

        test_progress = {
            "current_brand_index": 0,
            "current_brand": "oppo",
            "current_page": 2,
            "previous_list_brand": "oppo",
            "previous_list_page": 1,
            "previous_list_ids": [phone["id"] for phone in phones],
        }
        with mock.patch.object(pconline, "crawl_brand_list", return_value=["oppo"]):
            with mock.patch.object(pconline, "crawl_list_page", side_effect=fake_page):
                with mock.patch.object(pconline, "MAX_TIME_PER_STEP", 0):
                    with mock.patch.object(pconline, "MAX_PHONES_PER_RUN", 0):
                        with mock.patch.object(pconline, "progress", test_progress):
                            result = pconline._scan_all_models(object(), 0)

        all_phones, truncated, next_brand, next_page = result
        self.assertEqual(all_phones, [])
        self.assertTrue(truncated)
        self.assertEqual((next_brand, next_page), (0, 2))
        self.assertEqual(calls, [("oppo", 2)])

    def test_pconline_resume_rejects_older_page_replayed_at_cursor(self):
        page_one = [
            {
                "id": str(index),
                "name": f"第一页手机 {index}",
                "brand": "oppo",
                "url": f"https://example.invalid/{index}",
                "source": "太平洋电脑网",
            }
            for index in range(25)
        ]
        test_progress = {
            "current_brand_index": 0,
            "current_brand": "oppo",
            "current_page": 3,
            "previous_list_brand": "oppo",
            "previous_list_page": 2,
            "previous_list_ids": [str(100 + index) for index in range(25)],
            "list_page_fingerprints": {
                "oppo": {
                    "1": [phone["id"] for phone in page_one],
                    "2": [str(100 + index) for index in range(25)],
                }
            },
        }

        with mock.patch.object(pconline, "crawl_brand_list", return_value=["oppo"]):
            with mock.patch.object(
                pconline, "crawl_list_page", return_value=list(page_one)
            ):
                with mock.patch.object(pconline, "MAX_TIME_PER_STEP", 0):
                    with mock.patch.object(pconline, "MAX_PHONES_PER_RUN", 0):
                        with mock.patch.object(pconline, "progress", test_progress):
                            result = pconline._scan_all_models(object(), 0)

        all_phones, truncated, next_brand, next_page = result
        self.assertEqual(all_phones, [])
        self.assertTrue(truncated)
        self.assertEqual((next_brand, next_page), (0, 3))

    def test_pconline_repeated_full_page_is_incomplete_at_exact_page(self):
        phones = [
            {
                "id": str(index),
                "name": f"手机 {index}",
                "brand": "oppo",
                "url": f"https://example.invalid/{index}",
                "source": "太平洋电脑网",
            }
            for index in range(25)
        ]
        calls = []

        def fake_page(_session, brand, page):
            calls.append((brand, page))
            return list(phones)

        with mock.patch.object(pconline, "crawl_brand_list", return_value=["oppo"]):
            with mock.patch.object(pconline, "crawl_list_page", side_effect=fake_page):
                with mock.patch.object(pconline, "MAX_TIME_PER_STEP", 0):
                    with mock.patch.object(
                        pconline,
                        "progress",
                        {"current_brand_index": 0, "current_page": 1},
                    ):
                        result = pconline._scan_all_models(object(), 0)

        all_phones, truncated, next_brand, next_page = result
        self.assertEqual(len(all_phones), 25)
        self.assertTrue(truncated)
        self.assertEqual((next_brand, next_page), (0, 2))
        self.assertEqual(calls, [("oppo", 1), ("oppo", 2)])

    def test_pconline_retryable_detail_failure_does_not_starve_later_phone(self):
        candidates = [
            {
                "id": "retry-id",
                "name": "待重试手机",
                "brand": "oppo",
                "url": "https://example.invalid/retry-id",
                "source": "太平洋电脑网",
            },
            {
                "id": "good-id",
                "name": "有效手机",
                "brand": "oppo",
                "url": "https://example.invalid/good-id",
                "source": "太平洋电脑网",
            },
        ]
        test_progress = {
            "crawled_phones": [],
            "processed_phones": [],
            "skipped_phones": {},
            "total_phones": 0,
            "current_brand_index": 0,
            "current_brand": "oppo",
            "current_page": 1,
        }
        good_detail = {
            "phone_id": "good-id",
            "name": "有效手机",
            "上市时间": "2026年7月",
            "处理器": "测试处理器",
            "屏幕": "6.1英寸",
            "电池": "4000mAh",
            "url": "https://product.pconline.com.cn/mobile/oppo/good-id.html",
        }

        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "json"
            raw_dir.mkdir()
            progress_path = Path(tmp) / "progress.json"
            with mock.patch.object(pconline, "progress", test_progress):
                with mock.patch.object(pconline, "progress_file", str(progress_path)):
                    with mock.patch.object(pconline, "pconline_json_dir", str(raw_dir)):
                        with mock.patch.object(pconline, "INCREMENTAL_MODE", True):
                            with mock.patch.object(pconline, "AUTO_MODE", True):
                                with mock.patch.object(pconline, "MAX_TIME_PER_STEP", 0):
                                    with mock.patch.object(
                                        pconline, "MAX_PHONES_PER_RUN", 0
                                    ):
                                        with mock.patch.object(
                                            pconline,
                                            "_scan_all_models",
                                            return_value=(candidates, False, 1, 1),
                                        ):
                                            with mock.patch.object(
                                                pconline,
                                                "_get_existing_phone_ids",
                                                return_value=set(),
                                            ):
                                                with mock.patch.object(
                                                    pconline,
                                                    "crawl_detail_page",
                                                    side_effect=[None, good_detail],
                                                ):
                                                    with mock.patch.object(
                                                        pconline,
                                                        "get_session",
                                                        return_value=object(),
                                                    ):
                                                        with self.assertRaisesRegex(
                                                            SystemExit, "10"
                                                        ):
                                                            pconline.step1_crawl_list_and_detail()

            self.assertTrue((raw_dir / "good-id.json").is_file())

        self.assertEqual(
            (
                test_progress["current_brand_index"],
                test_progress["current_brand"],
                test_progress["current_page"],
            ),
            (0, "oppo", 1),
        )
        self.assertIn("good-id", test_progress["crawled_phones"])
        self.assertNotIn("retry-id", test_progress["skipped_phones"])

    def test_pconline_full_scan_detail_failure_does_not_starve_later_brand(self):
        retry = {
            "id": "retry-id",
            "name": "待重试手机",
            "brand": "oppo",
            "source": "太平洋电脑网",
        }
        later = {
            "id": "good-id",
            "name": "后续品牌手机",
            "brand": "honor",
            "source": "太平洋电脑网",
        }
        test_progress = {
            "crawled_phones": [],
            "processed_phones": [],
            "skipped_phones": {},
            "total_phones": 0,
            "current_brand_index": 0,
            "current_brand": "oppo",
            "current_page": 1,
        }
        good_detail = {
            "phone_id": "good-id",
            "name": "后续品牌手机",
            "上市时间": "2026年7月",
            "处理器": "测试处理器",
            "屏幕": "6.1英寸",
            "电池": "4000mAh",
            "url": "https://product.pconline.com.cn/mobile/honor/good-id.html",
        }

        def list_page(_session, brand, page):
            if page > 1:
                return []
            return [retry] if brand == "oppo" else [later]

        def detail(_session, phone_id, _brand):
            return None if phone_id == "retry-id" else good_detail

        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "json"
            raw_dir.mkdir()
            progress_path = Path(tmp) / "progress.json"
            with mock.patch.object(pconline, "progress", test_progress):
                with mock.patch.object(pconline, "progress_file", str(progress_path)):
                    with mock.patch.object(pconline, "pconline_json_dir", str(raw_dir)):
                        with mock.patch.object(pconline, "INCREMENTAL_MODE", False):
                            with mock.patch.object(pconline, "AUTO_MODE", True):
                                with mock.patch.object(pconline, "MAX_TIME_PER_STEP", 0):
                                    with mock.patch.object(
                                        pconline, "MAX_PHONES_PER_RUN", 0
                                    ):
                                        with mock.patch.object(
                                            pconline,
                                            "crawl_brand_list",
                                            return_value=["oppo", "honor"],
                                        ):
                                            with mock.patch.object(
                                                pconline,
                                                "crawl_list_page",
                                                side_effect=list_page,
                                            ):
                                                with mock.patch.object(
                                                    pconline,
                                                    "crawl_detail_page",
                                                    side_effect=detail,
                                                ):
                                                    with mock.patch.object(
                                                        pconline,
                                                        "get_session",
                                                        return_value=object(),
                                                    ):
                                                        with self.assertRaisesRegex(
                                                            SystemExit, "10"
                                                        ):
                                                            pconline.step1_crawl_list_and_detail()

            self.assertTrue((raw_dir / "good-id.json").is_file())

        self.assertEqual(
            (
                test_progress["current_brand"],
                test_progress["current_page"],
            ),
            ("oppo", 1),
        )

    def test_pconline_full_scan_rejects_nonadjacent_full_page_replay(self):
        page_one = [
            {
                "id": str(1000 + index),
                "name": f"第一页手机 {index}",
                "brand": "oppo",
                "source": "太平洋电脑网",
            }
            for index in range(25)
        ]
        page_two = [
            {
                "id": str(2000 + index),
                "name": f"第二页手机 {index}",
                "brand": "oppo",
                "source": "太平洋电脑网",
            }
            for index in range(25)
        ]
        test_progress = {
            "crawled_phones": [],
            "processed_phones": [],
            "skipped_phones": {},
            "total_phones": 0,
            "current_brand_index": 0,
            "current_brand": "oppo",
            "current_page": 1,
        }

        def list_page(_session, _brand, page):
            return {1: page_one, 2: page_two, 3: page_one}.get(page, [])

        with tempfile.TemporaryDirectory() as tmp:
            progress_path = Path(tmp) / "progress.json"
            with mock.patch.object(pconline, "progress", test_progress):
                with mock.patch.object(pconline, "progress_file", str(progress_path)):
                    with mock.patch.object(pconline, "INCREMENTAL_MODE", False):
                        with mock.patch.object(pconline, "AUTO_MODE", True):
                            with mock.patch.object(pconline, "MAX_TIME_PER_STEP", 0):
                                with mock.patch.object(
                                    pconline, "MAX_PHONES_PER_RUN", 0
                                ):
                                    with mock.patch.object(
                                        pconline,
                                        "crawl_brand_list",
                                        return_value=["oppo"],
                                    ):
                                        with mock.patch.object(
                                            pconline,
                                            "crawl_list_page",
                                            side_effect=list_page,
                                        ):
                                            with mock.patch.object(
                                                pconline,
                                                "crawl_detail_page",
                                                return_value={"上市时间": "2020年"},
                                            ):
                                                with mock.patch.object(
                                                    pconline,
                                                    "get_session",
                                                    return_value=object(),
                                                ):
                                                    with self.assertRaisesRegex(
                                                        SystemExit, "10"
                                                    ):
                                                        pconline.step1_crawl_list_and_detail()

        self.assertEqual(test_progress["current_brand"], "oppo")
        self.assertEqual(test_progress["current_page"], 3)
        self.assertFalse(test_progress["scan_complete"])

    def test_pconline_does_not_persist_or_process_semantically_thin_detail(self):
        candidate = {
            "id": "123",
            "name": "残缺手机",
            "brand": "oppo",
            "url": "https://product.pconline.com.cn/mobile/oppo/123.html",
            "source": "太平洋电脑网",
        }
        test_progress = {
            "crawled_phones": [],
            "processed_phones": [],
            "skipped_phones": {},
            "total_phones": 0,
            "current_brand_index": 0,
            "current_brand": "oppo",
            "current_page": 1,
        }

        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "json"
            raw_dir.mkdir()
            progress_path = Path(tmp) / "progress.json"
            with mock.patch.object(pconline, "progress", test_progress):
                with mock.patch.object(pconline, "progress_file", str(progress_path)):
                    with mock.patch.object(pconline, "pconline_json_dir", str(raw_dir)):
                        with mock.patch.object(pconline, "INCREMENTAL_MODE", True):
                            with mock.patch.object(pconline, "AUTO_MODE", True):
                                with mock.patch.object(pconline, "MAX_TIME_PER_STEP", 0):
                                    with mock.patch.object(
                                        pconline, "MAX_PHONES_PER_RUN", 0
                                    ):
                                        with mock.patch.object(
                                            pconline,
                                            "_scan_all_models",
                                            return_value=([candidate], False, 1, 1),
                                        ):
                                            with mock.patch.object(
                                                pconline,
                                                "_get_existing_phone_ids",
                                                return_value=set(),
                                            ):
                                                with mock.patch.object(
                                                    pconline,
                                                    "crawl_detail_page",
                                                    return_value={
                                                        "phone_id": "123",
                                                        "上市时间": "2026年7月",
                                                        "处理器": "测试处理器",
                                                    },
                                                ):
                                                    with mock.patch.object(
                                                        pconline,
                                                        "crawl_param_page",
                                                        return_value={},
                                                    ):
                                                        with mock.patch.object(
                                                            pconline,
                                                            "get_session",
                                                            return_value=object(),
                                                        ):
                                                            with self.assertRaisesRegex(
                                                                SystemExit, "10"
                                                            ):
                                                                pconline.step1_crawl_list_and_detail()

            self.assertFalse((raw_dir / "123.json").exists())

        self.assertNotIn("123", test_progress["processed_phones"])
        self.assertNotIn("123", test_progress["crawled_phones"])

    def test_pconline_parameter_page_can_complete_semantically_thin_detail(self):
        candidate = {
            "id": "123",
            "name": "可补全手机",
            "brand": "oppo",
            "url": "https://product.pconline.com.cn/mobile/oppo/123.html",
            "source": "太平洋电脑网",
        }
        test_progress = {
            "crawled_phones": [],
            "processed_phones": [],
            "skipped_phones": {},
            "total_phones": 0,
            "current_brand_index": 0,
            "current_brand": "oppo",
            "current_page": 1,
        }

        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "json"
            raw_dir.mkdir()
            progress_path = Path(tmp) / "progress.json"
            with (
                mock.patch.object(pconline, "progress", test_progress),
                mock.patch.object(pconline, "progress_file", str(progress_path)),
                mock.patch.object(pconline, "pconline_json_dir", str(raw_dir)),
                mock.patch.object(pconline, "INCREMENTAL_MODE", True),
                mock.patch.object(pconline, "AUTO_MODE", True),
                mock.patch.object(pconline, "MAX_TIME_PER_STEP", 0),
                mock.patch.object(pconline, "MAX_PHONES_PER_RUN", 0),
                mock.patch.object(
                    pconline,
                    "_scan_all_models",
                    return_value=([candidate], False, 1, 1),
                ),
                mock.patch.object(
                    pconline, "_get_existing_phone_ids", return_value=set()
                ),
                mock.patch.object(
                    pconline,
                    "crawl_detail_page",
                    return_value={
                        "phone_id": "123",
                        "上市时间": "2026年7月",
                        "处理器": "测试处理器",
                    },
                ),
                mock.patch.object(
                    pconline,
                    "crawl_param_page",
                    return_value={"屏幕": "6.1英寸", "电池": "4000mAh"},
                ) as param_page,
                mock.patch.object(pconline, "get_session", return_value=object()),
            ):
                pconline.step1_crawl_list_and_detail()

            self.assertTrue((raw_dir / "123.json").is_file())

        self.assertIn("123", test_progress["processed_phones"])
        self.assertIn("123", test_progress["crawled_phones"])
        param_page.assert_called_once()

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
