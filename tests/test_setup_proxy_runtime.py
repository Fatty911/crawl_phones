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

    def test_vless_reality_vision_link_round_trips_to_mihomo_yaml(self) -> None:
        link = (
            "vless://00000000-0000-0000-0000-000000000001@reality.example.test:443"
            "?security=reality"
            "&sni=www.microsoft.com"
            "&fp=chrome"
            "&pbk=sample-public-key"
            "&sid=abc123"
            "&spx=%2Fnews"
            "&type=tcp"
            "&flow=xtls-rprx-vision"
            "#RealityVision"
        )

        proxy = ClashConfigGenerator().parse_vless(link)

        self.assertIsNotNone(proxy)
        assert proxy is not None
        self.assertEqual("RealityVision", proxy["name"])
        self.assertEqual("vless", proxy["type"])
        self.assertEqual("reality.example.test", proxy["server"])
        self.assertEqual(443, proxy["port"])
        self.assertEqual("00000000-0000-0000-0000-000000000001", proxy["uuid"])
        self.assertTrue(proxy["tls"])
        self.assertEqual("none", proxy["encryption"])
        self.assertEqual("xtls-rprx-vision", proxy["flow"])
        self.assertEqual("www.microsoft.com", proxy["servername"])
        self.assertEqual("chrome", proxy["client-fingerprint"])
        self.assertEqual(
            {
                "public-key": "sample-public-key",
                "short-id": "abc123",
                "spider-x": "/news",
            },
            proxy["reality-opts"],
        )

        parsed = yaml.safe_load(ClashConfigGenerator().generate_config_from_proxies([proxy]))

        written_proxy = parsed["proxies"][0]
        self.assertEqual("none", written_proxy["encryption"])
        self.assertTrue(written_proxy["tls"])
        self.assertEqual("sample-public-key", written_proxy["reality-opts"]["public-key"])
        self.assertEqual("abc123", written_proxy["reality-opts"]["short-id"])
        self.assertIn("RealityVision", parsed["proxy-groups"][0]["proxies"])
        self.assertIn("RealityVision", parsed["proxy-groups"][1]["proxies"])

    def test_vless_reality_empty_short_id_is_omitted(self) -> None:
        link = (
            "vless://00000000-0000-0000-0000-000000000002@reality.example.test:443"
            "?security=reality"
            "&sni=www.microsoft.com"
            "&fp=chrome"
            "&pbk=sample-public-key"
            "&sid="
            "&type=tcp"
            "&flow=xtls-rprx-vision"
            "#EmptyShortId"
        )

        proxy = ClashConfigGenerator().parse_vless(link)

        self.assertIsNotNone(proxy)
        assert proxy is not None
        self.assertEqual("none", proxy["encryption"])
        self.assertTrue(proxy["tls"])
        self.assertEqual("sample-public-key", proxy["reality-opts"]["public-key"])
        self.assertNotIn("short-id", proxy["reality-opts"])

        parsed = yaml.safe_load(ClashConfigGenerator().generate_config_from_proxies([proxy]))

        self.assertNotIn("short-id", parsed["proxies"][0]["reality-opts"])

    def test_vless_reality_invalid_short_ids_are_omitted(self) -> None:
        invalid_short_ids = ("null", "None", "nil", "xyz", "abc", "001122334455667788")
        for short_id in invalid_short_ids:
            with self.subTest(short_id=short_id):
                link = (
                    "vless://00000000-0000-0000-0000-000000000003@reality.example.test:443"
                    "?security=reality"
                    "&sni=www.microsoft.com"
                    "&fp=chrome"
                    "&pbk=sample-public-key"
                    f"&sid={short_id}"
                    "&type=tcp"
                    "&flow=xtls-rprx-vision"
                    "#InvalidShortId"
                )

                proxy = ClashConfigGenerator().parse_vless(link)

                self.assertIsNotNone(proxy)
                assert proxy is not None
                self.assertEqual("sample-public-key", proxy["reality-opts"]["public-key"])
                self.assertNotIn("short-id", proxy["reality-opts"])

    def test_vless_reality_uppercase_short_id_is_preserved(self) -> None:
        link = (
            "vless://00000000-0000-0000-0000-000000000004@reality.example.test:443"
            "?security=reality"
            "&sni=www.microsoft.com"
            "&fp=chrome"
            "&pbk=sample-public-key"
            "&sid=ABCDEF"
            "&type=tcp"
            "&flow=xtls-rprx-vision"
            "#UppercaseShortId"
        )

        proxy = ClashConfigGenerator().parse_vless(link)

        self.assertIsNotNone(proxy)
        assert proxy is not None
        self.assertEqual("ABCDEF", proxy["reality-opts"]["short-id"])

    def test_generated_proxy_yaml_sanitizes_invalid_reality_short_id(self) -> None:
        parsed = yaml.safe_load(
            ClashConfigGenerator().generate_config_from_proxies(
                [
                    {
                        "name": "RawReality",
                        "type": "vless",
                        "server": "reality.example.test",
                        "port": 443,
                        "uuid": "00000000-0000-0000-0000-000000000005",
                        "tls": True,
                        "flow": "xtls-rprx-vision",
                        "client-fingerprint": "chrome",
                        "reality-opts": {
                            "public-key": "sample-public-key",
                            "short-id": "null",
                            "spider-x": "/news",
                        },
                    }
                ]
            )
        )

        reality_opts = parsed["proxies"][0]["reality-opts"]
        self.assertEqual("sample-public-key", reality_opts["public-key"])
        self.assertEqual("/news", reality_opts["spider-x"])
        self.assertNotIn("short-id", reality_opts)

    def test_generated_proxy_yaml_quotes_reality_short_ids(self) -> None:
        config = ClashConfigGenerator().generate_config_from_proxies(
            [
                {
                    "name": "LeadingZeroReality",
                    "type": "vless",
                    "server": "reality.example.test",
                    "port": 443,
                    "uuid": "00000000-0000-0000-0000-000000000006",
                    "tls": True,
                    "reality-opts": {
                        "public-key": "sample-public-key",
                        "short-id": "09561058",
                    },
                },
                {
                    "name": "ScientificNotationReality",
                    "type": "vless",
                    "server": "reality.example.test",
                    "port": 443,
                    "uuid": "00000000-0000-0000-0000-000000000007",
                    "tls": True,
                    "reality-opts": {
                        "public-key": "sample-public-key",
                        "short-id": "34010e92",
                    },
                },
            ]
        )

        self.assertIn("short-id: '09561058'", config)
        self.assertIn("short-id: '34010e92'", config)
        parsed = yaml.safe_load(config)
        self.assertEqual("09561058", parsed["proxies"][0]["reality-opts"]["short-id"])
        self.assertEqual("34010e92", parsed["proxies"][1]["reality-opts"]["short-id"])

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
