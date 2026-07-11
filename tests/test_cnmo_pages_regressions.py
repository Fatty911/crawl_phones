from __future__ import annotations

import importlib.util
import json
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
        self.assertEqual("1065", metrics["totalCount"])
        self.assertEqual("931", metrics["zolCount"])
        self.assertEqual("663", metrics["pconlineCount"])
        self.assertEqual("35", metrics["cnmoCount"])
        self.assertEqual("547", metrics["verifiedCount"])
        self.assertIn("1065", metrics["dataMeta"])


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
                        {"手机ID": "keep", "型号": "保留", "上市时间": "2025", "价格": "1"},
                        {"手机ID": "update", "型号": "更新", "上市时间": "2026", "价格": "old"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (json_dir / "update.json").write_text(
                json.dumps({"手机ID": "update", "型号": "更新", "上市时间": "2026", "价格": "new"}, ensure_ascii=False),
                encoding="utf-8",
            )
            with (
                mock.patch.object(self.cnmo, "data_dir", str(data_dir)),
                mock.patch.object(self.cnmo, "cnmo_json_dir", str(json_dir)),
            ):
                rows = self.cnmo.step2_parse_and_merge()

            by_id = {row["手机ID"]: row for row in rows}
            self.assertEqual({"keep", "update"}, set(by_id))
            self.assertEqual("new", by_id["update"]["价格"])

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


class CnmoWorkflowTests(unittest.TestCase):
    def test_workflow_targets_cnmo_proxy_and_marks_done_only_on_complete_scan(self) -> None:
        text = (ROOT / ".github/workflows/crawl-cnmo.yml").read_text(encoding="utf-8")
        self.assertIn(
            'scripts/setup_proxy_runtime.py --github-env "$GITHUB_ENV" --test-url "https://product.cnmo.com/all/product_t1_p1.html"',
            text,
        )
        mark_step = text.split("- name: Mark crawl complete and commit", 1)[1].split("- name: Upload crawl data", 1)[0]
        self.assertNotIn("steps.validate_data.outputs.has_data", mark_step)
        self.assertIn('if [ "$DEBUG_MODE" = "true" ] && [ "${MAX_PHONES:-0}" -le 0 ]; then', text)
        configure_step = text.split("- name: Configure crawl window", 1)[1].split("- name: Set up Python", 1)[0]
        self.assertIn("DEBUG_MODE: ${{ github.event.inputs.debug_mode || 'false' }}", configure_step)
        self.assertIn("p['incremental_scan_page']=1", text)
        resumable_block = text.split("if [ $EXIT_CODE -eq 10 ]; then", 1)[1].split("elif [ $EXIT_CODE -ne 0 ]; then", 1)[0]
        self.assertNotIn("git add", resumable_block)
        self.assertNotIn("git_sync_progress.sh", resumable_block)


if __name__ == "__main__":
    unittest.main()
