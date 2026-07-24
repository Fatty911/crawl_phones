from __future__ import annotations

import io
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_clash_config import ClashConfigGenerator  # type: ignore[reportMissingImports]  # noqa: E402
import setup_proxy_runtime as proxy_runtime  # type: ignore[reportMissingImports]  # noqa: E402


class SetupProxyRuntimeTests(unittest.TestCase):
    def test_generated_proxy_yaml_quotes_special_characters(self) -> None:
        name = "HK: node #1 [test] \"quote\" 'single'\t tab"
        config_text = ClashConfigGenerator().generate_config_from_proxies(
            [
                {
                    "name": name,
                    "type": "trojan",
                    "server": "edge.example.test",
                    "port": 443,
                    "password": "pa:ss #hash [bracket]\t tab",
                    "network": "ws",
                    "ws-opts": {
                        "path": "/ws:path#frag",
                        "headers": {"Host": "edge.example.test:443"},
                    },
                    "skip-cert-verify": False,
                    "udp": True,
                    "optional-none": None,
                }
            ]
        )

        parsed = yaml.safe_load(config_text)

        self.assertEqual(name, parsed["proxies"][0]["name"])
        self.assertEqual("pa:ss #hash [bracket]\t tab", parsed["proxies"][0]["password"])
        self.assertNotIn("optional-none", parsed["proxies"][0])
        self.assertIn(name, parsed["proxy-groups"][0]["proxies"])
        self.assertIn(name, parsed["proxy-groups"][1]["proxies"])

    def test_enabled_proxy_bypasses_github_artifact_endpoints(self) -> None:
        captured: dict[str, str] = {}
        process = SimpleNamespace(pid=1234, terminate=lambda: None)

        with (
            mock.patch.dict(os.environ, {"PROXY_SUBSCRIPTIONS": "https://example.test/sub"}),
            mock.patch.object(sys, "argv", ["setup_proxy_runtime.py", "--github-env", "github.env"]),
            mock.patch.object(proxy_runtime, "parse_proxy_secret", return_value=(["https://example.test/sub"], [])),
            mock.patch.object(proxy_runtime, "parse_nodes", return_value=[{"name": "test"}]),
            mock.patch.object(proxy_runtime, "write_runtime_files"),
            mock.patch.object(proxy_runtime, "find_mihomo", return_value=Path("mihomo")),
            mock.patch.object(proxy_runtime.subprocess, "Popen", return_value=process),
            mock.patch.object(proxy_runtime.Path, "open", return_value=io.BytesIO()),
            mock.patch.object(proxy_runtime, "wait_for_controller", return_value=True),
            mock.patch.object(proxy_runtime, "test_local_proxy", return_value=True),
            mock.patch.object(proxy_runtime, "append_github_env", side_effect=lambda _path, values: captured.update(values)),
        ):
            self.assertEqual(0, proxy_runtime.main())

        expected = (
            "127.0.0.1,localhost,"
            "results-receiver.actions.githubusercontent.com,.blob.core.windows.net"
        )
        self.assertEqual(expected, captured["NO_PROXY"])
        self.assertEqual(expected, captured["no_proxy"])


if __name__ == "__main__":
    unittest.main()
