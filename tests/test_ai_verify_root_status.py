from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ai_verify_root_status.py"
sys.path.insert(0, str(ROOT / "scripts"))
import ai_verify_root_status as ai_verify  # type: ignore[reportMissingImports]  # noqa: E402


class AiVerifyRootStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.originals = {
            "NIM_KEY": ai_verify.NIM_KEY,
            "OR_KEY": ai_verify.OR_KEY,
            "NIM_MODELS": ai_verify.NIM_MODELS,
            "OR_FREE_MODELS": ai_verify.OR_FREE_MODELS,
            "MIN_REQUEST_INTERVAL": ai_verify.MIN_REQUEST_INTERVAL,
            "_last_request_time": ai_verify._last_request_time,
            "DATA_FILE": ai_verify.DATA_FILE,
            "CACHE_FILE": ai_verify.CACHE_FILE,
            "OUTPUT_FILE": ai_verify.OUTPUT_FILE,
            "MAX_WORKERS": ai_verify.MAX_WORKERS,
            "TOTAL_TIME_BUDGET": ai_verify.TOTAL_TIME_BUDGET,
            "FINALIZE_TIME_BUFFER": ai_verify.FINALIZE_TIME_BUFFER,
        }
        setattr(ai_verify, "NIM_KEY", "nim-secret-sentinel")
        setattr(ai_verify, "OR_KEY", "or-secret-sentinel")
        setattr(ai_verify, "NIM_MODELS", [f"nim-{index}" for index in range(4)])
        setattr(ai_verify, "OR_FREE_MODELS", [f"or-{index}" for index in range(2)])
        setattr(ai_verify, "MIN_REQUEST_INTERVAL", 0)
        setattr(ai_verify, "_last_request_time", 0)

    def tearDown(self) -> None:
        for name, value in self.originals.items():
            setattr(ai_verify, name, value)

    def test_failures_are_structured_and_secrets_are_redacted(self) -> None:
        def fail_nim(prompt: str, model: str, timeout: float) -> None:
            raise RuntimeError(f"nim failed with {ai_verify.NIM_KEY}")

        def fail_openrouter(prompt: str, model: str, timeout: float) -> None:
            raise TimeoutError(f"openrouter failed with {ai_verify.OR_KEY}")

        stderr = io.StringIO()
        with (
            mock.patch.object(ai_verify, "_try_nim", side_effect=fail_nim),
            mock.patch.object(ai_verify, "_try_or", side_effect=fail_openrouter),
            mock.patch.object(ai_verify.time, "sleep", return_value=None),
            contextlib.redirect_stderr(stderr),
        ):
            result = ai_verify.ai_query("prompt", retries=3, deadline=time.monotonic() + 60)

        self.assertIsNone(result)
        output = stderr.getvalue()
        self.assertNotIn("nim-secret-sentinel", output)
        self.assertNotIn("or-secret-sentinel", output)

        events = [
            json.loads(line)
            for line in output.splitlines()
            if line.startswith("{")
        ]
        self.assertEqual(10, len(events))
        for event in events:
            self.assertEqual("ai_request_failed", event["event"])
            self.assertTrue(event["timestamp_utc"].endswith("Z"))
            self.assertIn(event["provider"], {"nim", "openrouter"})
            self.assertTrue(event["model"])
            self.assertTrue(event["source_url"].startswith("https://"))
            self.assertGreaterEqual(event["attempt"], 1)
            self.assertEqual(event["attempt"] - 1, event["retry_count"])
            self.assertTrue(event["error_type"])
            self.assertIn("***", event["error_message"])

        nim_events = [event for event in events if event["provider"] == "nim"]
        self.assertTrue(all(event["max_attempts"] == 1 for event in nim_events))
        openrouter_events = [event for event in events if event["provider"] == "openrouter"]
        self.assertEqual([1, 2, 3, 1, 2, 3], [event["attempt"] for event in openrouter_events])

    def test_concurrent_failure_events_remain_one_json_object_per_line(self) -> None:
        class FragmentingStream:
            def __init__(self) -> None:
                self.parts: list[str] = []

            def write(self, text: str) -> int:
                middle = len(text) // 2
                self.parts.append(text[:middle])
                time.sleep(0.001)
                self.parts.append(text[middle:])
                return len(text)

            def flush(self) -> None:
                return None

            def getvalue(self) -> str:
                return "".join(self.parts)

        stream = FragmentingStream()
        with mock.patch.object(ai_verify.sys, "stderr", stream):
            with ai_verify.concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                futures = [
                    executor.submit(
                        ai_verify._log_ai_failure,
                        "nim",
                        f"model-{index}",
                        ai_verify.NIM_ENDPOINT,
                        1,
                        1,
                        RuntimeError("boom"),
                    )
                    for index in range(20)
                ]
                for future in futures:
                    future.result()

        events = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual(20, len(events))
        self.assertEqual({f"model-{index}" for index in range(20)}, {event["model"] for event in events})

    def test_expired_deadline_stops_before_network_request(self) -> None:
        with (
            mock.patch.object(ai_verify, "_try_nim") as try_nim,
            mock.patch.object(ai_verify, "_try_or") as try_openrouter,
        ):
            result = ai_verify.ai_query("prompt", deadline=time.monotonic() - 1)

        self.assertIsNone(result)
        try_nim.assert_not_called()
        try_openrouter.assert_not_called()

    def test_request_timeout_is_clamped_to_remaining_budget(self) -> None:
        with mock.patch.object(ai_verify.time, "monotonic", return_value=100.0):
            self.assertEqual(5.0, ai_verify._request_timeout(105.0))
            self.assertIsNone(ai_verify._request_timeout(100.0))

    def test_blocking_request_process_is_terminated_at_deadline(self) -> None:
        before = {process.pid for process in ai_verify.multiprocessing.active_children()}
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            ai_verify._run_in_subprocess(time.sleep, (2,), 0.05)
        self.assertLess(time.monotonic() - started, 1.5)
        after = {process.pid for process in ai_verify.multiprocessing.active_children()}
        self.assertEqual(set(), after - before)

    def test_budget_exhaustion_skips_second_stage_and_saves_completed_result(self) -> None:
        original_as_completed = ai_verify.concurrent.futures.as_completed

        def yield_one_then_timeout(futures, timeout):
            for future in original_as_completed(futures):
                yield future
                break
            raise ai_verify.concurrent.futures.TimeoutError()

        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "phones.json"
            cache_path = Path(tmp) / "cache.json"
            data_path.write_text(
                json.dumps([{"品牌": "小米", "型号": "测试手机", "处理器": "骁龙 8 Gen3", "root或越狱": "未知"}], ensure_ascii=False),
                encoding="utf-8",
            )
            setattr(ai_verify, "DATA_FILE", str(data_path))
            setattr(ai_verify, "OUTPUT_FILE", str(data_path))
            setattr(ai_verify, "CACHE_FILE", str(cache_path))
            setattr(ai_verify, "MAX_WORKERS", 1)
            setattr(ai_verify, "TOTAL_TIME_BUDGET", 5)
            setattr(ai_verify, "FINALIZE_TIME_BUFFER", 1)

            completed = {"conclusion": "可永久root", "method": "Magisk"}
            with (
                mock.patch.object(ai_verify, "verify_brand_soc_group", return_value=completed),
                mock.patch.object(ai_verify, "verify_single_model") as verify_single,
                mock.patch.object(ai_verify.concurrent.futures, "as_completed", side_effect=yield_one_then_timeout),
            ):
                ai_verify.main()

            verify_single.assert_not_called()
            rows = json.loads(data_path.read_text(encoding="utf-8"))
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual("可永久root（Magisk）", rows[0]["root或越狱"])
            self.assertEqual("可永久root（Magisk）", cache["测试手机"])

    def test_main_loop_uses_iterator_timeout_not_completed_future_timeout(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("concurrent.futures.as_completed(", source)
        self.assertIn("timeout=max(_remaining_seconds(deadline)", source)
        self.assertNotIn("future.result(timeout=", source)
        self.assertIn("品牌SOC阶段已耗尽时间预算，跳过单机型查询", source)


if __name__ == "__main__":
    unittest.main()
