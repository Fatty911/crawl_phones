from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests


ROOT = Path(__file__).resolve().parents[1]


def load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.object(sys, "argv", [path.name]):
        spec.loader.exec_module(module)
    return module


class PagesFilteringTests(unittest.TestCase):
    def test_pages_filters_2022_plus_and_computes_cards_from_filtered_rows(self) -> None:
        node = r"""
const fs = require("fs");
const vm = require("vm");

class Element {
  constructor(id) {
    this.id = id;
    this._textContent = "";
    this.children = [];
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this.dataset = {};
    this.className = "";
    this.tagName = "DIV";
    this.title = "";
  }
  set textContent(value) { this._textContent = String(value); this.children = []; }
  get textContent() { return this._textContent; }
  appendChild(child) { this.children.push(child); return child; }
  addEventListener() {}
  matches() { return false; }
  closest() { return null; }
  remove() {}
  click() {}
}

const elements = new Map();
function getElement(id) {
  if (!elements.has(id)) elements.set(id, new Element(id));
  return elements.get(id);
}
const document = {
  getElementById: getElement,
  createElement(tag) { const el = new Element(""); el.tagName = tag.toUpperCase(); return el; },
  createDocumentFragment() { return new Element(""); },
  addEventListener() {},
  body: new Element("body"),
};
const localStorage = { getItem() { return null; }, setItem() {} };
const rows = JSON.parse(fs.readFileSync("docs/phones/data/latest.json", "utf8"));
rows.push(
  {"型号": "非法年份前缀", "上市时间": "12022", "数据来源": "CNMO", "验证状态": "单源"},
  {"型号": "非法年份后缀", "上市时间": "20220", "数据来源": "CNMO", "验证状态": "单源"},
  {"型号": "缺失年份", "上市时间": "", "数据来源": "CNMO", "验证状态": "单源"},
  {"型号": "三源计数样本", "上市时间": "2026年07月", "数据来源": "中关村在线+太平洋电脑网+CNMO", "验证状态": "三源一致"},
);
const staleManifest = {
  date: "test",
  rowCount: 9999,
  sourceCounts: {"中关村在线": 9999, "太平洋电脑网": 9999, "CNMO": 9999},
  files: {latestJson: "data/latest.json", latestCsv: "data/latest.csv"},
};
function fetch(url) {
  const payload = url.includes("manifest") ? staleManifest : rows;
  return Promise.resolve({ok: true, json: () => Promise.resolve(payload)});
}
const sandbox = {
  console, document, localStorage, fetch,
  Blob: class Blob {},
  URL: {createObjectURL() { return "blob:test"; }, revokeObjectURL() {}},
  Set, Map, Array, Object, String, Number, Boolean, Math, Date, JSON, Promise,
  setTimeout, clearTimeout,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("docs/phones/app.js", "utf8"), sandbox);
setTimeout(() => {
  const ids = ["totalCount", "zolCount", "pconlineCount", "cnmoCount", "verifiedCount", "dataMeta"];
  const output = Object.fromEntries(ids.map((id) => [id, getElement(id).textContent]));
  process.stdout.write(JSON.stringify(output));
}, 50);
"""
        result = subprocess.run(
            ["node", "-e", node],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        metrics = json.loads(result.stdout)
        rows = json.loads((ROOT / "docs/phones/data/latest.json").read_text(encoding="utf-8"))
        rows.append(
            {
                "型号": "三源计数样本",
                "上市时间": "2026年07月",
                "数据来源": "中关村在线+太平洋电脑网+CNMO",
                "验证状态": "三源一致",
            }
        )

        def release_year(row):
            for field in ["上市时间", "国内发布时间", "发布时间", "发布日期", "上市日期"]:
                match = re.search(r"(^|[^\d])((?:19|20)\d{2})(?!\d)", str(row.get(field, "")))
                if match:
                    return int(match.group(2))
            return None

        filtered = [row for row in rows if (release_year(row) or 0) >= 2022]
        source_count = lambda source: sum(source in str(row.get("数据来源", "")) for row in filtered)
        verified_count = sum(
            re.fullmatch(r"[双三]源(?:一致|差异)", str(row.get("验证状态", ""))) is not None
            for row in filtered
        )
        self.assertEqual(str(len(filtered)), metrics["totalCount"])
        self.assertEqual(str(source_count("中关村在线")), metrics["zolCount"])
        self.assertEqual(str(source_count("太平洋电脑网")), metrics["pconlineCount"])
        self.assertEqual(str(source_count("CNMO")), metrics["cnmoCount"])
        self.assertEqual(str(verified_count), metrics["verifiedCount"])
        self.assertIn(str(len(filtered)), metrics["dataMeta"])


class CnmoCrawlerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cnmo = load_script_module("crawl_cnmo_regression", ROOT / "scripts" / "crawl_cnmo.py")

    def test_list_request_failure_is_not_reported_as_end_of_pagination(self) -> None:
        session = mock.Mock()
        session.get.side_effect = requests.exceptions.SSLError("proxy eof")
        with mock.patch.object(self.cnmo, "human_delay", return_value=None):
            with self.assertRaises(RuntimeError):
                self.cnmo.crawl_list_page(session, 1)

    def test_list_request_timeout_is_wrapped_with_cause(self) -> None:
        session = mock.Mock()
        timeout = requests.exceptions.Timeout("read timed out")
        session.get.side_effect = timeout
        with mock.patch.object(self.cnmo, "human_delay", return_value=None):
            with self.assertRaises(self.cnmo.ListPageFetchError) as raised:
                self.cnmo.crawl_list_page(session, 29)

        self.assertIs(raised.exception.__cause__, timeout)

    def test_list_launch_time_is_used_for_release_year(self) -> None:
        self.assertEqual(
            2026,
            self.cnmo.extract_release_year({"launch_time": "2026年09月"}),
        )

    def test_list_fields_are_normalized_for_output(self) -> None:
        normalized = self.cnmo.normalize_phone_fields(
            {"launch_time": "2026年09月", "price": "暂无报价"}
        )
        self.assertEqual("2026年09月", normalized["上市时间"])
        self.assertEqual("", normalized["价格"])
        self.assertNotIn("launch_time", normalized)
        self.assertNotIn("price", normalized)

    def test_cnmo_price_is_numeric_or_empty(self) -> None:
        cases = {
            "￥3,999": "3999",
            "3999.00": "3999.00",
            "2026年09月": "",
            "暂无报价": "",
            "3999元起": "",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(expected, self.cnmo.normalize_cnmo_price(raw))

    def test_future_release_uses_available_date_precision(self) -> None:
        run_day = self.cnmo.date(2026, 7, 12)
        self.assertFalse(self.cnmo.is_future_release({"上市时间": "2026年07月12日"}, run_day))
        self.assertTrue(self.cnmo.is_future_release({"上市时间": "2026年07月13日"}, run_day))
        self.assertFalse(self.cnmo.is_future_release({"上市时间": "2026年07月"}, run_day))
        self.assertTrue(self.cnmo.is_future_release({"上市时间": "2026年08月"}, run_day))
        self.assertTrue(self.cnmo.is_future_release({"上市时间": "2027年"}, run_day))
        self.assertFalse(self.cnmo.is_future_release({"上市时间": "待定"}, run_day))

    def test_step1_saves_list_launch_time_when_detail_has_no_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            json_dir = root / "json"
            data_dir.mkdir()
            json_dir.mkdir()
            progress_path = root / "progress.json"
            progress = {"crawled_pages": [], "crawled_phones": [], "current_page": 1, "total_phones": 0}
            with (
                mock.patch.object(self.cnmo, "data_dir", str(data_dir)),
                mock.patch.object(self.cnmo, "cnmo_json_dir", str(json_dir)),
                mock.patch.object(self.cnmo, "progress_file", str(progress_path)),
                mock.patch.object(self.cnmo, "progress", progress),
                mock.patch.object(self.cnmo, "INCREMENTAL_MODE", True),
                mock.patch.object(self.cnmo, "MAX_PAGES_PER_RUN", 0),
                mock.patch.object(self.cnmo, "MAX_PHONES_PER_RUN", 1),
                mock.patch.object(self.cnmo, "MAX_TIME_PER_STEP", 0),
                mock.patch.object(self.cnmo, "AUTO_MODE", False),
                mock.patch.object(self.cnmo, "get_session", return_value=mock.Mock()),
                mock.patch.object(
                    self.cnmo,
                    "crawl_list_page",
                    side_effect=[
                        [
                            {
                                "id": "new",
                                "name": "新机",
                                "price": "暂无报价",
                                "launch_time": "2026年06月",
                            }
                        ],
                        [],
                    ],
                ),
                mock.patch.object(
                    self.cnmo,
                    "crawl_detail_page",
                    return_value={"CPU型号": "测试处理器"},
                ),
            ):
                self.cnmo.step1_crawl_list_and_detail()

            saved = json.loads((json_dir / "new.json").read_text(encoding="utf-8"))
            self.assertEqual("2026年06月", saved["上市时间"])
            self.assertEqual("", saved["价格"])
            self.assertNotIn("launch_time", saved)
            self.assertNotIn("price", saved)
            self.assertEqual(["new"], progress["crawled_phones"])
            self.assertEqual(1, progress["total_phones"])

    def test_incremental_mode_seeds_existing_ids_from_previous_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            json_dir = root / "json"
            data_dir.mkdir()
            json_dir.mkdir()
            (data_dir / "cnmo_phones_20260710.json").write_text(
                json.dumps([{"手机ID": "old", "型号": "旧机", "上市时间": "2026"}], ensure_ascii=False),
                encoding="utf-8",
            )
            progress_path = root / "progress.json"
            progress = {"crawled_pages": [], "crawled_phones": [], "current_page": 1, "total_phones": 0}
            detail = mock.Mock(return_value={"型号": "新机", "上市时间": "2026"})
            with (
                mock.patch.object(self.cnmo, "data_dir", str(data_dir)),
                mock.patch.object(self.cnmo, "cnmo_json_dir", str(json_dir)),
                mock.patch.object(self.cnmo, "progress_file", str(progress_path)),
                mock.patch.object(self.cnmo, "progress", progress),
                mock.patch.object(self.cnmo, "INCREMENTAL_MODE", True),
                mock.patch.object(self.cnmo, "MAX_PAGES_PER_RUN", 1),
                mock.patch.object(self.cnmo, "MAX_PHONES_PER_RUN", 10),
                mock.patch.object(self.cnmo, "MAX_TIME_PER_STEP", 0),
                mock.patch.object(self.cnmo, "AUTO_MODE", False),
                mock.patch.object(self.cnmo, "get_session", return_value=mock.Mock()),
                mock.patch.object(
                    self.cnmo,
                    "crawl_list_page",
                    side_effect=[
                        [
                            {"id": "old", "name": "旧机", "price": "", "launch_time": ""},
                            {"id": "new", "name": "新机", "price": "", "launch_time": ""},
                        ]
                    ],
                ),
                mock.patch.object(self.cnmo, "crawl_detail_page", detail),
            ):
                self.cnmo.step1_crawl_list_and_detail()

            detail.assert_called_once_with(mock.ANY, "new")
            self.assertTrue((json_dir / "new.json").exists())

    def test_incremental_list_fetch_error_exits_10_and_preserves_failed_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            json_dir = root / "json"
            data_dir.mkdir()
            json_dir.mkdir()
            progress_path = root / "progress.json"
            progress = {
                "crawled_pages": [],
                "crawled_phones": ["old"],
                "current_page": 1,
                "total_phones": 1,
                "incremental_scan_page": 1,
            }
            with (
                mock.patch.object(self.cnmo, "data_dir", str(data_dir)),
                mock.patch.object(self.cnmo, "cnmo_json_dir", str(json_dir)),
                mock.patch.object(self.cnmo, "progress_file", str(progress_path)),
                mock.patch.object(self.cnmo, "progress", progress),
                mock.patch.object(self.cnmo, "INCREMENTAL_MODE", True),
                mock.patch.object(self.cnmo, "MAX_PAGES_PER_RUN", 0),
                mock.patch.object(self.cnmo, "MAX_PHONES_PER_RUN", 0),
                mock.patch.object(self.cnmo, "MAX_TIME_PER_STEP", 0),
                mock.patch.object(self.cnmo, "AUTO_MODE", True),
                mock.patch.object(self.cnmo, "get_session", return_value=mock.Mock()),
                mock.patch.object(
                    self.cnmo,
                    "crawl_list_page",
                    side_effect=[
                        [{"id": "old", "name": "旧机", "price": "", "launch_time": ""}],
                        self.cnmo.ListPageFetchError("page 2 timeout"),
                    ],
                ),
                mock.patch.object(self.cnmo, "crawl_detail_page") as detail,
            ):
                with self.assertRaises(SystemExit) as raised:
                    self.cnmo.step1_crawl_list_and_detail()

            self.assertEqual(10, raised.exception.code)
            self.assertEqual(2, progress["incremental_scan_page"])
            saved = json.loads(progress_path.read_text(encoding="utf-8"))
            self.assertEqual(2, saved["incremental_scan_page"])
            detail.assert_not_called()

    def test_incremental_plain_runtime_error_is_not_swallowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            json_dir = root / "json"
            data_dir.mkdir()
            json_dir.mkdir()
            progress_path = root / "progress.json"
            progress = {"crawled_pages": [], "crawled_phones": [], "current_page": 1, "total_phones": 0}
            with (
                mock.patch.object(self.cnmo, "data_dir", str(data_dir)),
                mock.patch.object(self.cnmo, "cnmo_json_dir", str(json_dir)),
                mock.patch.object(self.cnmo, "progress_file", str(progress_path)),
                mock.patch.object(self.cnmo, "progress", progress),
                mock.patch.object(self.cnmo, "INCREMENTAL_MODE", True),
                mock.patch.object(self.cnmo, "MAX_PAGES_PER_RUN", 0),
                mock.patch.object(self.cnmo, "MAX_PHONES_PER_RUN", 0),
                mock.patch.object(self.cnmo, "MAX_TIME_PER_STEP", 0),
                mock.patch.object(self.cnmo, "AUTO_MODE", True),
                mock.patch.object(self.cnmo, "get_session", return_value=mock.Mock()),
                mock.patch.object(self.cnmo, "crawl_list_page", side_effect=RuntimeError("parse bug")),
            ):
                with self.assertRaisesRegex(RuntimeError, "parse bug"):
                    self.cnmo.step1_crawl_list_and_detail()

            self.assertFalse(progress_path.exists())

    def test_debug_limit_counts_this_run_not_historical_total(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            json_dir = root / "json"
            data_dir.mkdir()
            json_dir.mkdir()
            progress_path = root / "progress.json"
            progress = {"crawled_pages": [], "crawled_phones": [], "current_page": 1, "total_phones": 30}
            detail = mock.Mock(return_value={"型号": "新机", "上市时间": "2026"})
            with (
                mock.patch.object(self.cnmo, "data_dir", str(data_dir)),
                mock.patch.object(self.cnmo, "cnmo_json_dir", str(json_dir)),
                mock.patch.object(self.cnmo, "progress_file", str(progress_path)),
                mock.patch.object(self.cnmo, "progress", progress),
                mock.patch.object(self.cnmo, "INCREMENTAL_MODE", True),
                mock.patch.object(self.cnmo, "MAX_PAGES_PER_RUN", 1),
                mock.patch.object(self.cnmo, "MAX_PHONES_PER_RUN", 1),
                mock.patch.object(self.cnmo, "MAX_TIME_PER_STEP", 0),
                mock.patch.object(self.cnmo, "AUTO_MODE", False),
                mock.patch.object(self.cnmo, "get_session", return_value=mock.Mock()),
                mock.patch.object(
                    self.cnmo,
                    "crawl_list_page",
                    return_value=[{"id": "new", "name": "新机", "price": "", "launch_time": ""}],
                ),
                mock.patch.object(self.cnmo, "crawl_detail_page", detail),
            ):
                self.cnmo.step1_crawl_list_and_detail()

            detail.assert_called_once_with(mock.ANY, "new")
            self.assertEqual(31, progress["total_phones"])

    def test_step2_accumulates_previous_output_and_prefers_fresh_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            json_dir = root / "json"
            data_dir.mkdir()
            json_dir.mkdir()
            (data_dir / "cnmo_phones_20260710.json").write_text(
                json.dumps(
                    [
                        {"手机ID": "keep", "型号": "保留", "上市时间": "2025", "价格": "100"},
                        {"手机ID": "update", "型号": "更新", "上市时间": "2026", "价格": "150"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (json_dir / "update.json").write_text(
                json.dumps({"手机ID": "update", "型号": "更新", "上市时间": "2026", "价格": "200"}, ensure_ascii=False),
                encoding="utf-8",
            )
            with (
                mock.patch.object(self.cnmo, "data_dir", str(data_dir)),
                mock.patch.object(self.cnmo, "cnmo_json_dir", str(json_dir)),
            ):
                rows = self.cnmo.step2_parse_and_merge()

            by_id = {row["手机ID"]: row for row in rows}
            self.assertEqual({"keep", "update"}, set(by_id))
            self.assertEqual("200", by_id["update"]["价格"])

    def test_full_scan_page_limit_is_resumable_not_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            json_dir = root / "json"
            data_dir.mkdir()
            json_dir.mkdir()
            progress_path = root / "progress.json"
            progress = {"crawled_pages": [], "crawled_phones": [], "current_page": 1, "total_phones": 0}
            with (
                mock.patch.object(self.cnmo, "data_dir", str(data_dir)),
                mock.patch.object(self.cnmo, "cnmo_json_dir", str(json_dir)),
                mock.patch.object(self.cnmo, "progress_file", str(progress_path)),
                mock.patch.object(self.cnmo, "progress", progress),
                mock.patch.object(self.cnmo, "INCREMENTAL_MODE", False),
                mock.patch.object(self.cnmo, "MAX_PAGES_PER_RUN", 1),
                mock.patch.object(self.cnmo, "MAX_PHONES_PER_RUN", 0),
                mock.patch.object(self.cnmo, "MAX_TIME_PER_STEP", 0),
                mock.patch.object(self.cnmo, "AUTO_MODE", True),
                mock.patch.object(self.cnmo, "get_session", return_value=mock.Mock()),
                mock.patch.object(
                    self.cnmo,
                    "crawl_list_page",
                    return_value=[{"id": "new", "name": "新机", "price": "", "launch_time": ""}],
                ) as crawl_list,
                mock.patch.object(self.cnmo, "crawl_detail_page", return_value={"型号": "新机", "上市时间": "2026"}),
            ):
                with self.assertRaises(SystemExit) as raised:
                    self.cnmo.step1_crawl_list_and_detail()
                crawl_list.assert_called_once_with(mock.ANY, 1)
                crawl_list.reset_mock()
                with self.assertRaises(SystemExit) as second_raised:
                    self.cnmo.step1_crawl_list_and_detail()

            self.assertEqual(10, raised.exception.code)
            self.assertEqual(10, second_raised.exception.code)
            crawl_list.assert_called_once_with(mock.ANY, 2)
            self.assertEqual(3, progress["current_page"])

    def test_full_scan_phone_limit_counts_this_run_not_historical_total(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            json_dir = root / "json"
            data_dir.mkdir()
            json_dir.mkdir()
            progress_path = root / "progress.json"
            progress = {"crawled_pages": [], "crawled_phones": [], "current_page": 1, "total_phones": 50}
            detail = mock.Mock(return_value={"型号": "新机", "上市时间": "2026"})
            with (
                mock.patch.object(self.cnmo, "data_dir", str(data_dir)),
                mock.patch.object(self.cnmo, "cnmo_json_dir", str(json_dir)),
                mock.patch.object(self.cnmo, "progress_file", str(progress_path)),
                mock.patch.object(self.cnmo, "progress", progress),
                mock.patch.object(self.cnmo, "INCREMENTAL_MODE", False),
                mock.patch.object(self.cnmo, "MAX_PAGES_PER_RUN", 0),
                mock.patch.object(self.cnmo, "MAX_PHONES_PER_RUN", 1),
                mock.patch.object(self.cnmo, "MAX_TIME_PER_STEP", 0),
                mock.patch.object(self.cnmo, "AUTO_MODE", True),
                mock.patch.object(self.cnmo, "get_session", return_value=mock.Mock()),
                mock.patch.object(
                    self.cnmo,
                    "crawl_list_page",
                    return_value=[{"id": "new", "name": "新机", "price": "", "launch_time": ""}],
                ) as crawl_list,
                mock.patch.object(self.cnmo, "crawl_detail_page", detail),
            ):
                with self.assertRaises(SystemExit) as raised:
                    self.cnmo.step1_crawl_list_and_detail()

            self.assertEqual(10, raised.exception.code)
            crawl_list.assert_called_once_with(mock.ANY, 1)
            detail.assert_called_once_with(mock.ANY, "new")
            self.assertEqual(51, progress["total_phones"])

    def test_incremental_page_limit_resumes_at_next_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            json_dir = root / "json"
            data_dir.mkdir()
            json_dir.mkdir()
            progress_path = root / "progress.json"
            progress = {
                "crawled_pages": [],
                "crawled_phones": [],
                "current_page": 1,
                "incremental_scan_page": 1,
                "total_phones": 0,
            }

            def list_page(_session, page):
                return [{"id": f"p{page}", "name": f"第{page}页", "price": "", "launch_time": ""}]

            with (
                mock.patch.object(self.cnmo, "data_dir", str(data_dir)),
                mock.patch.object(self.cnmo, "cnmo_json_dir", str(json_dir)),
                mock.patch.object(self.cnmo, "progress_file", str(progress_path)),
                mock.patch.object(self.cnmo, "progress", progress),
                mock.patch.object(self.cnmo, "INCREMENTAL_MODE", True),
                mock.patch.object(self.cnmo, "MAX_PAGES_PER_RUN", 1),
                mock.patch.object(self.cnmo, "MAX_PHONES_PER_RUN", 0),
                mock.patch.object(self.cnmo, "MAX_TIME_PER_STEP", 0),
                mock.patch.object(self.cnmo, "AUTO_MODE", True),
                mock.patch.object(self.cnmo, "get_session", return_value=mock.Mock()),
                mock.patch.object(self.cnmo, "crawl_list_page", side_effect=list_page) as crawl_list,
                mock.patch.object(self.cnmo, "crawl_detail_page", return_value={"型号": "新机", "上市时间": "2026"}),
            ):
                with self.assertRaises(SystemExit) as first:
                    self.cnmo.step1_crawl_list_and_detail()
                with self.assertRaises(SystemExit) as second:
                    self.cnmo.step1_crawl_list_and_detail()

            self.assertEqual(10, first.exception.code)
            self.assertEqual(10, second.exception.code)
            self.assertEqual([1, 2], [call.args[1] for call in crawl_list.call_args_list])
            self.assertEqual(3, progress["incremental_scan_page"])

    def test_detail_failure_is_resumable_and_does_not_advance_full_page(self) -> None:
        for incremental in (True, False):
            with self.subTest(incremental=incremental), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                data_dir = root / "data"
                json_dir = root / "json"
                data_dir.mkdir()
                json_dir.mkdir()
                progress_path = root / "progress.json"
                progress = {
                    "crawled_pages": [],
                    "crawled_phones": [],
                    "current_page": 1,
                    "incremental_scan_page": 1,
                    "total_phones": 0,
                }
                list_results = [
                    [{"id": "failed", "name": "失败机型", "price": "", "launch_time": ""}],
                    [],
                ]
                with (
                    mock.patch.object(self.cnmo, "data_dir", str(data_dir)),
                    mock.patch.object(self.cnmo, "cnmo_json_dir", str(json_dir)),
                    mock.patch.object(self.cnmo, "progress_file", str(progress_path)),
                    mock.patch.object(self.cnmo, "progress", progress),
                    mock.patch.object(self.cnmo, "INCREMENTAL_MODE", incremental),
                    mock.patch.object(self.cnmo, "MAX_PAGES_PER_RUN", 0),
                    mock.patch.object(self.cnmo, "MAX_PHONES_PER_RUN", 0),
                    mock.patch.object(self.cnmo, "MAX_TIME_PER_STEP", 0),
                    mock.patch.object(self.cnmo, "AUTO_MODE", True),
                    mock.patch.object(self.cnmo, "get_session", return_value=mock.Mock()),
                    mock.patch.object(self.cnmo, "crawl_list_page", side_effect=list_results),
                    mock.patch.object(self.cnmo, "crawl_detail_page", return_value=None),
                ):
                    with self.assertRaises(SystemExit) as raised:
                        self.cnmo.step1_crawl_list_and_detail()

                self.assertEqual(10, raised.exception.code)
                self.assertEqual(1, progress["current_page"])
                self.assertEqual(1, progress["incremental_scan_page"])
                self.assertNotIn("failed", progress["crawled_phones"])


class CnmoParamUrlResolutionTests(unittest.TestCase):
    """Regression: parameter page href from CNMO list/detail page can be
    protocol-relative (//product.cnmo.com/...) or path-absolute with
    duplicated domain (/product.cnmo.com/...). Naive BASE_URL + href
    concatenation produced https://product.cnmo.com//product.cnmo.com/...
    causing all 6700 detail fetches to 404."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.cnmo = load_script_module("crawl_cnmo_paramurl", ROOT / "scripts" / "crawl_cnmo.py")

    def test_protocol_relative_href_resolves_without_duplicated_domain(self) -> None:
        """href='//product.cnmo.com/1628/1627858/param.shtml' must NOT
        become https://product.cnmo.com//product.cnmo.com/..."""
        resolved = self.cnmo.resolve_param_url(
            "//product.cnmo.com/1628/1627858/param.shtml"
        )
        self.assertEqual(
            "https://product.cnmo.com/1628/1627858/param.shtml",
            resolved,
        )

    def test_absolute_href_returned_as_is(self) -> None:
        resolved = self.cnmo.resolve_param_url(
            "https://product.cnmo.com/cell_phone/123/param.shtml"
        )
        self.assertEqual(
            "https://product.cnmo.com/cell_phone/123/param.shtml",
            resolved,
        )

    def test_path_absolute_with_domain_stripped(self) -> None:
        """href='/product.cnmo.com/1628/1627858/param.shtml' must NOT
        produce https://product.cnmo.com/product.cnmo.com/..."""
        resolved = self.cnmo.resolve_param_url(
            "/product.cnmo.com/1628/1627858/param.shtml"
        )
        self.assertEqual(
            "https://product.cnmo.com/1628/1627858/param.shtml",
            resolved,
        )

    def test_simple_relative_href_joins_to_base(self) -> None:
        resolved = self.cnmo.resolve_param_url("cell_phone/123/param.shtml")
        self.assertEqual(
            "https://product.cnmo.com/cell_phone/123/param.shtml",
            resolved,
        )

    def test_directory_relative_href_joins_against_detail_page(self) -> None:
        resolved = self.cnmo.resolve_param_url(
            "123/param.shtml",
            "https://product.cnmo.com/cell_phone/index123.shtml",
        )
        self.assertEqual(
            "https://product.cnmo.com/cell_phone/123/param.shtml",
            resolved,
        )

    def test_path_absolute_without_domain_joins(self) -> None:
        resolved = self.cnmo.resolve_param_url("/cell_phone/123/param.shtml")
        self.assertEqual(
            "https://product.cnmo.com/cell_phone/123/param.shtml",
            resolved,
        )

    def test_http_absolute_url_preserved(self) -> None:
        resolved = self.cnmo.resolve_param_url(
            "http://product.cnmo.com/cell_phone/123/param.shtml"
        )
        self.assertEqual(
            "http://product.cnmo.com/cell_phone/123/param.shtml",
            resolved,
        )

    def test_cross_origin_absolute_and_protocol_relative_urls_are_rejected(self) -> None:
        self.assertIsNone(
            self.cnmo.resolve_param_url("https://evil.example/123/param.shtml")
        )
        self.assertIsNone(
            self.cnmo.resolve_param_url("//evil.example/123/param.shtml")
        )

    def test_embedded_domain_prefix_requires_path_boundary(self) -> None:
        self.assertIsNone(
            self.cnmo.resolve_param_url(
                "/product.cnmo.com.evil/123/param.shtml"
            )
        )

    def test_query_and_fragment_are_preserved_for_param_path(self) -> None:
        resolved = self.cnmo.resolve_param_url(
            "//product.cnmo.com/123/param.shtml?from=detail#specs"
        )
        self.assertEqual(
            "https://product.cnmo.com/123/param.shtml?from=detail#specs",
            resolved,
        )

    def test_param_name_in_query_does_not_make_non_param_path_valid(self) -> None:
        self.assertIsNone(
            self.cnmo.resolve_param_url(
                "https://product.cnmo.com/redirect.shtml?next=param.shtml"
            )
        )

    def test_empty_or_blank_href_returns_none(self) -> None:
        self.assertIsNone(self.cnmo.resolve_param_url(""))
        self.assertIsNone(self.cnmo.resolve_param_url("   "))

    def test_parameter_http_failure_returns_none(self) -> None:
        detail_response = requests.Response()
        detail_response.status_code = 200
        detail_response._content = (
            b'<html><h1>Test Phone</h1>'
            b'<a href="//product.cnmo.com/123/param.shtml">params</a></html>'
        )
        parameter_response = requests.Response()
        parameter_response.status_code = 404
        session = mock.Mock()
        session.get.side_effect = [detail_response, parameter_response]

        self.assertIsNone(self.cnmo.crawl_detail_page(session, "123"))
        self.assertEqual(
            "https://product.cnmo.com/123/param.shtml",
            session.get.call_args_list[1].args[0],
        )


class ThreeSourceValidationStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.merge = load_script_module("merge_phones_three_source", ROOT / "scripts" / "merge_phones.py")

    @staticmethod
    def source_row(seed: str, **overrides: str) -> dict[str, str]:
        row = {
            "处理器": f"处理器-{seed}",
            "内存": f"内存-{seed}",
            "存储": f"存储-{seed}",
            "屏幕": f"屏幕-{seed}",
            "电池": f"电池-{seed}",
            "摄像头参数": f"摄像头-{seed}",
            "上市时间": f"2026年0{seed}月01日",
        }
        row.update(overrides)
        return row

    def test_three_complete_equal_sources_are_three_source_consistent(self) -> None:
        rows = {
            "中关村在线": self.source_row("1"),
            "太平洋电脑网": self.source_row("1"),
            "CNMO": self.source_row("1"),
        }

        status, differences = self.merge.classify_source_agreement(rows)

        self.assertEqual("三源一致", status)
        self.assertEqual("-", differences)

    def test_each_possible_equal_pair_is_dual_source_consistent(self) -> None:
        source_names = ("中关村在线", "太平洋电脑网", "CNMO")
        for equal_pair in ((0, 1), (0, 2), (1, 2)):
            with self.subTest(equal_pair=equal_pair):
                rows = {
                    name: self.source_row("1" if index in equal_pair else "2")
                    for index, name in enumerate(source_names)
                }

                status, differences = self.merge.classify_source_agreement(rows)

                self.assertEqual("双源一致", status)
                self.assertNotEqual("-", differences)

    def test_three_complete_different_sources_are_three_source_different(self) -> None:
        rows = {
            "中关村在线": self.source_row("1"),
            "太平洋电脑网": self.source_row("2"),
            "CNMO": self.source_row("3"),
        }

        status, differences = self.merge.classify_source_agreement(rows)

        self.assertEqual("三源差异", status)
        self.assertIn("处理器", differences)

    def test_missing_key_field_never_counts_as_source_consistency(self) -> None:
        rows = {
            "中关村在线": self.source_row("1"),
            "太平洋电脑网": self.source_row("1", 电池="暂无"),
            "CNMO": self.source_row("1"),
        }

        status, differences = self.merge.classify_source_agreement(rows)

        self.assertEqual("多源未校验", status)
        self.assertIn("太平洋电脑网缺失电池", differences)


    def test_cnmo_match_reclassifies_from_actual_three_source_values(self) -> None:
        shared = self.source_row("1")
        zol = [{"型号": "测试 Pro（12GB/512GB）", **shared}]
        pconline = [{"型号": "测试 Pro（12GB/512GB）", **shared}]
        cnmo = [{"型号": "测试 Pro(12GB+512GB)", **shared}]
        fields = self.merge.FIXED + list(self.merge.VALIDATION_FIELDS)

        merged = self.merge.merge_verified_rows(zol, pconline, fields)
        appended, matched = self.merge.append_unique_single_source(merged, cnmo, "CNMO")

        self.assertEqual([], appended)
        self.assertEqual(1, matched)
        self.assertEqual("中关村在线+太平洋电脑网+CNMO", merged[0]["数据来源"])
        self.assertEqual("三源一致", merged[0]["验证状态"])
        self.assertEqual("-", merged[0]["交叉验证差异"])


    def test_raw_cnmo_aliases_are_normalized_before_three_source_classification(self) -> None:
        shared = self.source_row("1")
        raw_cnmo = {
            "型号": "测试 Pro(12GB+512GB)",
            **{key: value for key, value in shared.items() if key not in {"电池", "摄像头参数"}},
            "电池类型": shared["电池"],
            "后置相机": shared["摄像头参数"],
        }
        normalized_cnmo = self.merge.norm_rows([raw_cnmo], "CNMO")[0]
        zol = [{"型号": "测试 Pro（12GB/512GB）", **shared}]
        pconline = [{"型号": "测试 Pro（12GB/512GB）", **shared}]
        fields = self.merge.FIXED + list(self.merge.VALIDATION_FIELDS)

        merged = self.merge.merge_verified_rows(zol, pconline, fields)
        appended, matched = self.merge.append_unique_single_source(merged, [normalized_cnmo], "CNMO")

        self.assertEqual([], appended)
        self.assertEqual(1, matched)
        self.assertEqual(shared["电池"], normalized_cnmo["电池"])
        self.assertEqual(shared["摄像头参数"], normalized_cnmo["摄像头参数"])
        self.assertEqual("三源一致", merged[0]["验证状态"])


class MergeCnmoCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.merge = load_script_module("merge_phones_regression", ROOT / "scripts" / "merge_phones.py")

    def test_matching_capacity_adds_cnmo_coverage_without_faking_verification(self) -> None:
        base = [
            {"型号": "测试 Pro（8GB/256GB）", "数据来源": "中关村在线", "验证状态": "单源"},
            {"型号": "测试 Pro（12GB/512GB）", "数据来源": "中关村在线", "验证状态": "单源"},
        ]
        extra = [{"型号": "测试 Pro(12GB+512GB)", "数据来源": "CNMO", "验证状态": "单源"}]
        appended, matched = self.merge.append_unique_single_source(base, extra, "CNMO")

        self.assertEqual([], appended)
        self.assertEqual(1, matched)
        self.assertEqual("中关村在线", base[0]["数据来源"])
        self.assertEqual("中关村在线+CNMO", base[1]["数据来源"])
        self.assertEqual("多源未校验", base[1]["验证状态"])

    def test_conflicting_source_ids_keep_cnmo_baseline_identity(self) -> None:
        base = [
            {
                "手机ID": "1397100",
                "品牌": "荣耀",
                "型号": "荣耀Magic3",
                "存储": "128GB•手机rom是什么•查看所有128GB荣耀,256GB",
                "内存": "8GB",
                "数据来源": "太平洋电脑网",
                "验证状态": "单源",
            }
        ]
        extra = [
            {
                "手机ID": "1624724",
                "品牌": "荣耀",
                "型号": "荣耀Magic3(8+128GB)",
                "存储": "128GB",
                "内存": "8GB",
                "数据来源": "CNMO",
                "验证状态": "单源",
            }
        ]
        appended, matched = self.merge.append_unique_single_source(base, extra, "CNMO")

        self.assertEqual([], appended)
        self.assertEqual(1, matched)
        self.assertEqual("1397100", base[0]["手机ID"])
        self.assertEqual("太平洋电脑网+CNMO", base[0]["数据来源"])
        self.assertEqual("1397100|1624724", base[0]["关联手机ID"])

    def test_cnmo_single_source_scope_keeps_china_and_global_best_sellers(self) -> None:
        allowed_rows = [
            {"品牌": "荣耀", "型号": "荣耀X80i(8GB+256GB)"},
            {"品牌": "苹果", "型号": "苹果iPhone16 Pro Max(1TB)"},
            {"品牌": "三星", "型号": "三星Galaxy S26 Ultra(16GB+1TB)"},
            {"品牌": "", "型号": "WIKO Hi 畅享 60s(256GB)"},
            {"品牌": "", "型号": "Hi畅享60s(256GB)"},
            {"品牌": "", "型号": "ROG游戏手机9 Pro(24+1TB)"},
            {"品牌": "", "型号": "Hi nova 10 Pro(8+256GB)"},
            {"品牌": "", "型号": "天翼铂顿S9 5G"},
        ]

        for row in allowed_rows:
            with self.subTest(model=row["型号"]):
                self.assertTrue(self.merge.is_cnmo_single_source_in_publish_scope(row))

    def test_cnmo_single_source_scope_filters_regional_or_non_target_brands(self) -> None:
        filtered_rows = [
            {"品牌": "谷歌", "型号": "谷歌Pixel 8 Pro"},
            {"品牌": "索尼", "型号": "索尼Xperia 1 V(12GB+512GB)"},
            {"品牌": "传音", "型号": "Infinix GT 20 Pro"},
            {"品牌": "诺基亚", "型号": "Nokia 105 4G"},
            {"品牌": "LG", "型号": "LG G9"},
            {"品牌": "", "型号": "ObscureLand X1(4GB+128GB)"},
        ]

        for row in filtered_rows:
            with self.subTest(model=row["型号"]):
                self.assertFalse(self.merge.is_cnmo_single_source_in_publish_scope(row))

    def test_cnmo_capacity_shorthand_matches_full_unit_variant(self) -> None:
        base = [
            {
                "型号": "HUAWEI Mate 60 Pro（12GB/1TB）",
                "数据来源": "中关村在线",
                "验证状态": "单源",
            }
        ]
        extra = [{"型号": "华为Mate60 Pro(12+1T)", "数据来源": "CNMO", "验证状态": "单源"}]
        appended, matched = self.merge.append_unique_single_source(base, extra, "CNMO")

        self.assertEqual(self.merge.model_key(base[0]), self.merge.model_key(extra[0]))
        self.assertEqual((12, 1024), self.merge.model_storage_signature(extra[0]))
        self.assertEqual([], appended)
        self.assertEqual(1, matched)
        self.assertEqual("中关村在线+CNMO", base[0]["数据来源"])
        self.assertEqual("多源未校验", base[0]["验证状态"])

    def test_capacity_parentheses_with_5g_annotation_do_not_match_plain_capacity(self) -> None:
        base = [
            {
                "型号": "测试 Pro（12GB/1TB/5G版）",
                "数据来源": "中关村在线",
                "验证状态": "单源",
            }
        ]
        extra = [{"型号": "测试 Pro(12+1T)", "数据来源": "CNMO", "验证状态": "单源"}]
        appended, matched = self.merge.append_unique_single_source(base, extra, "CNMO")

        self.assertNotEqual(self.merge.model_key(base[0]), self.merge.model_key(extra[0]))
        self.assertEqual(0, matched)
        self.assertEqual(1, len(appended))
        self.assertEqual("中关村在线", base[0]["数据来源"])
        self.assertEqual("CNMO", appended[0]["数据来源"])

    def test_capacity_signature_must_not_match_a_capacity_unknown_base_row(self) -> None:
        base = [{"型号": "测试 Pro", "数据来源": "中关村在线", "验证状态": "单源"}]
        extra = [{"型号": "测试 Pro(12+1T)", "数据来源": "CNMO", "验证状态": "单源"}]
        appended, matched = self.merge.append_unique_single_source(base, extra, "CNMO")

        self.assertEqual((), self.merge.model_storage_signature(base[0]))
        self.assertEqual((12, 1024), self.merge.model_storage_signature(extra[0]))
        self.assertEqual(0, matched)
        self.assertEqual(1, len(appended))
        self.assertEqual("中关村在线", base[0]["数据来源"])

    def test_capacity_and_model_annotations_do_not_cross_match(self) -> None:
        cases = [
            ("测试 Pro（12GB/512GB）", "测试 Pro(12+1T)"),
            ("测试 Pro+", "测试 Pro"),
            ("测试 Pro(5G版)", "测试 Pro"),
        ]
        for base_name, extra_name in cases:
            with self.subTest(base=base_name, extra=extra_name):
                base = [{"型号": base_name, "数据来源": "中关村在线", "验证状态": "单源"}]
                extra = [{"型号": extra_name, "数据来源": "CNMO", "验证状态": "单源"}]
                appended, matched = self.merge.append_unique_single_source(base, extra, "CNMO")

                self.assertEqual(0, matched)
                self.assertEqual(1, len(appended))
                self.assertEqual("中关村在线", base[0]["数据来源"])



    def test_zol_pconline_capacity_variants_do_not_cross_merge(self) -> None:
        zol = [{"型号": "测试 Pro（8GB/256GB）", "品牌": "测试", "数据来源": "中关村在线"}]
        pconline = [{"型号": "测试 Pro（12GB/512GB）", "品牌": "测试", "数据来源": "太平洋电脑网"}]
        fields = self.merge.FIXED + ["品牌"]

        merged = self.merge.merge_verified_rows(zol, pconline, fields)

        self.assertEqual(2, len(merged))
        self.assertEqual(["中关村在线", "太平洋电脑网"], [row["数据来源"] for row in merged])

    def test_zol_pconline_matching_one_capacity_does_not_drop_other_pconline_variants(self) -> None:
        zol = [{"型号": "测试 Pro（8GB/256GB）", "品牌": "测试", "数据来源": "中关村在线"}]
        pconline = [
            {"型号": "测试 Pro（8GB/256GB）", "品牌": "测试", "数据来源": "太平洋电脑网"},
            {"型号": "测试 Pro（12GB/512GB）", "品牌": "测试", "数据来源": "太平洋电脑网"},
        ]
        fields = self.merge.FIXED + ["品牌"]

        merged = self.merge.merge_verified_rows(zol, pconline, fields)

        self.assertEqual(2, len(merged))
        self.assertEqual("中关村在线+太平洋电脑网", merged[0]["数据来源"])
        self.assertEqual("太平洋电脑网", merged[1]["数据来源"])

    def test_trailing_capacity_text_is_removed_without_merging_plus_models(self) -> None:
        equal_pairs = [
            ("华为畅享 90 256GB", "华为畅享 90(256GB)"),
            ("华为nova 12 256GB", "华为nova 12(256GB)"),
            ("华为Pura 90 12GB+512GB", "华为 Pura90(12GB+512GB)"),
        ]
        for left, right in equal_pairs:
            with self.subTest(left=left, right=right):
                self.assertEqual(self.merge.model_key({"型号": left}), self.merge.model_key({"型号": right}))

        different_pairs = [
            ("OPPO Find X8s(16GB/1TB)", "OPPO Find X8s+(16GB+1TB)"),
            ("荣耀70 Pro（8GB/256GB）", "荣耀70 Pro+(8+256GB)"),
        ]
        for left, right in different_pairs:
            with self.subTest(left=left, right=right):
                self.assertNotEqual(self.merge.model_key({"型号": left}), self.merge.model_key({"型号": right}))

    def test_storage_signature_reads_irregular_and_field_capacity_formats(self) -> None:
        cases = {
            "vivo X300s()16GB/+512GB": (16, 512),
            "vivo X300s(16GB+512GB)": (16, 512),
            "一加11（12GB/256GB/5G版）": (12, 256),
            "华为Pura 90 12GB+512GB": (12, 512),
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(expected, self.merge.model_storage_signature({"型号": name}))
        self.assertEqual((16, 512), self.merge.model_storage_signature({"型号": "测试 Pro", "内存": "16GB", "存储": "512GB"}))

    def test_ambiguous_or_different_capacity_stays_as_independent_cnmo_row(self) -> None:
        base = [
            {"型号": "测试 Pro（8GB/256GB）", "数据来源": "中关村在线", "验证状态": "单源"},
            {"型号": "测试 Pro（12GB/512GB）", "数据来源": "太平洋电脑网", "验证状态": "单源"},
        ]
        extra = [{"型号": "测试 Pro(16GB+1TB)", "数据来源": "CNMO", "验证状态": "单源"}]
        appended, matched = self.merge.append_unique_single_source(base, extra, "CNMO")

        self.assertEqual(0, matched)
        self.assertEqual(1, len(appended))
        self.assertEqual("CNMO", appended[0]["数据来源"])
        self.assertTrue(all("CNMO" not in row["数据来源"] for row in base))

    def test_cnmo_load_all_prefers_latest_dated_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            old_path = data_dir / "cnmo_phones_20260710.json"
            new_path = data_dir / "cnmo_phones_20260711.json"
            old_path.write_text(json.dumps([{"手机ID": "same", "价格": "old"}]), encoding="utf-8")
            new_path.write_text(json.dumps([{"手机ID": "same", "价格": "new"}]), encoding="utf-8")
            original_root = getattr(self.merge, "ROOT")
            setattr(self.merge, "ROOT", str(root))
            try:
                rows = self.merge.load_all("data/cnmo_phones_*.json", prefer_latest=True)
            finally:
                setattr(self.merge, "ROOT", original_root)

            self.assertEqual(1, len(rows))
            self.assertEqual("new", rows[0]["价格"])

    def test_publish_guard_drops_future_rows_and_sanitizes_cnmo_price(self) -> None:
        run_day = self.merge.date(2026, 7, 12)
        rows = [
            {"型号": "今天", "上市时间": "2026年07月12日", "价格": "￥3999"},
            {"型号": "未来月", "上市时间": "2026年08月", "价格": "2026年08月"},
            {"型号": "未知", "上市时间": "待定", "价格": "暂无报价"},
        ]
        guarded = self.merge.guard_publish_rows(rows, source="CNMO", today=run_day)
        self.assertEqual(["今天", "未知"], [row["型号"] for row in guarded])
        self.assertEqual(["3999", ""], [row["价格"] for row in guarded])


class PagesPaginationContractTests(unittest.TestCase):
    def test_pages_keep_adjacent_buttons_and_add_jump_controls(self) -> None:
        html = (ROOT / "docs/phones/index.html").read_text(encoding="utf-8")
        script = (ROOT / "docs/phones/app.js").read_text(encoding="utf-8")
        self.assertIn('id="prevPage"', html)
        self.assertIn('id="nextPage"', html)
        self.assertIn('id="pageJump"', html)
        self.assertIn('id="jumpPage"', html)
        self.assertIn("function jumpToPage()", script)
        self.assertIn("多源未校验", script)

    def test_pages_count_two_and_three_source_comparisons_as_verified(self) -> None:
        script = (ROOT / "docs/phones/app.js").read_text(encoding="utf-8")
        self.assertIn('/^[双三]源(?:一致|差异)$/', script)
        self.assertIn("双源或三源仅统计已实际比对记录", script)


class CnmoDatasetValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = load_script_module(
            "validate_cnmo_dataset_regression",
            ROOT / "scripts" / "validate_cnmo_dataset.py",
        )

    @staticmethod
    def complete_raw_row(index: int) -> dict[str, str]:
        return {
            "型号": f"测试手机 {index}",
            "处理器": "处理器",
            "内存": "12GB",
            "存储": "256GB",
            "屏幕": "6.7英寸",
            "电池类型": "锂聚合物电池,5000mAh",
            "后置相机": "5000万像素",
            "上市时间": "2026年07月",
        }

    def test_raw_cnmo_aliases_satisfy_normalized_key_fields(self) -> None:
        rows = [self.complete_raw_row(index) for index in range(20)]

        report = self.validator.dataset_quality(rows)

        self.assertEqual(100, report["valid_rate"])
        self.assertEqual(20, report["model_count"])
        self.assertEqual(20, report["field_counts"]["电池"])
        self.assertEqual(20, report["field_counts"]["摄像头参数"])
        self.assertTrue(self.validator.is_valid_dataset(rows, debug=True))

    def test_debug_dataset_rejects_model_and_date_only_rows(self) -> None:
        rows = [
            {"型号": f"测试手机 {index}", "上市时间": "2026年07月"}
            for index in range(20)
        ]

        self.assertFalse(self.validator.is_valid_dataset(rows, debug=True))

    def test_debug_dataset_enforces_twenty_to_thirty_rows(self) -> None:
        self.assertFalse(
            self.validator.is_valid_dataset(
                [self.complete_raw_row(index) for index in range(19)],
                debug=True,
            )
        )
        self.assertFalse(
            self.validator.is_valid_dataset(
                [self.complete_raw_row(index) for index in range(31)],
                debug=True,
            )
        )


class CnmoWorkflowTests(unittest.TestCase):
    def test_workflow_targets_cnmo_proxy_and_marks_done_only_on_complete_scan(self) -> None:
        text = (ROOT / ".github/workflows/crawl-cnmo.yml").read_text(encoding="utf-8")
        self.assertIn(
            'scripts/setup_proxy_runtime.py --github-env "$GITHUB_ENV" --test-url "https://product.cnmo.com/all/product_t1_p1.html"',
            text,
        )
        mark_step = text.split("- name: Mark crawl complete and commit", 1)[1].split("- name: Upload crawl data", 1)[0]
        self.assertIn("steps.validate_data.outputs.has_data", mark_step)
        self.assertIn("MIN_CNMO_COMPLETE_ROWS=200", mark_step)
        self.assertIn('CNMO_ROW_COUNT="${{ steps.validate_data.outputs.cnmo_row_count }}"', mark_step)
        self.assertIn('if [ "$CNMO_ROW_COUNT" -ge "$MIN_CNMO_COMPLETE_ROWS" ] && [ "${{ steps.validate_data.outputs.has_data }}" = "true" ]; then', mark_step)
        self.assertIn('if [ "$DEBUG_LIMIT" = "0" ]; then DEBUG_LIMIT=30; fi', text)
        configure_step = text.split("- name: Configure crawl window", 1)[1].split("- name: Set up Python", 1)[0]
        self.assertIn("DEBUG_MODE: ${{ github.event.inputs.debug_mode || 'false' }}", configure_step)
        validate_step = text.split("- name: Validate generated CNMO data", 1)[1].split("- name: Generate summary", 1)[0]
        self.assertIn('if [ "${{ github.event.inputs.debug_mode || \'false\' }}" = "true" ]; then', validate_step)
        self.assertIn('python3 scripts/validate_cnmo_dataset.py "$DATA_FILE" --debug', validate_step)
        self.assertIn('python3 scripts/validate_cnmo_dataset.py "$DATA_FILE"', validate_step)
        self.assertIn("七个关键字段完整率不低于 70%", validate_step)
        self.assertIn("p['incremental_scan_page']=1", text)
        resumable_block = text.split("if [ $EXIT_CODE -eq 10 ]; then", 1)[1].split("elif [ $EXIT_CODE -ne 0 ]; then", 1)[0]
        self.assertNotIn("git add", resumable_block)
        self.assertNotIn("git_sync_progress.sh", resumable_block)

    def test_merge_completion_requires_cnmo_done_marker(self) -> None:
        text = (ROOT / ".github/workflows/merge-and-deploy.yml").read_text(encoding="utf-8")
        check_step = text.split("- name: 检查半月周期是否完成", 1)[1].split("  merge-data:", 1)[0]
        self.assertIn('CNMO_DONE="crawl_state/cnmo_${CRAWL_PERIOD}.done"', check_step)
        self.assertIn('[ -f "$ZOL_DONE" ] && [ -f "$PCONLINE_DONE" ] && [ -f "$CNMO_DONE" ]', check_step)
        self.assertIn("三个爬虫都已完成", check_step)
        self.assertIn("CNMO完成:", check_step)

    def test_independent_pages_deploy_rejects_tiny_or_shrinking_release(self) -> None:
        text = (ROOT / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
        self.assertIn('if [ "$ROWS" -lt 10 ]; then', text)
        tiny_release_block = text.split('if [ "$ROWS" -lt 10 ]; then', 1)[1].split('DATE=$(basename "$MERGED_JSON"', 1)[0]
        self.assertIn("continue", tiny_release_block)
        self.assertIn("--pattern 'merged_phones_*.json'", text)
        self.assertIn("MERGED_JSON=$(ls release-files/merged_phones_*.json", text)
        self.assertIn('cp release-files/merged_phones_*.csv "site/data/merged_phones_${DATE}.csv"', text)
        self.assertIn("scripts/verify_publish_superset.py /tmp/phones-pages-baseline.json site/data/latest.json", text)
        self.assertIn("scripts/verify_publish_superset.py docs/phones/data/latest.json site/data/latest.json", text)
        self.assertNotIn("跳过超集校验", text)


if __name__ == "__main__":
    unittest.main()
