import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import zipfile

import pytest

SPEC = importlib.util.spec_from_file_location(
    "cnb_pages_bridge", Path(__file__).resolve().parents[1] / "scripts" / "prepare_cnb_pages.py"
)
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


def payload(tmp_path, files=None, extra=None):
    manifest = json.dumps({"updatedAt": "2026-01-02T03:04:05Z", "files": files or {"latestJson": "data/latest.json"}}).encode()
    expected = tmp_path / "manifest.json"
    expected.write_bytes(manifest)
    archive = tmp_path / "verified-site.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("index.html", "<html>verified</html>")
        bundle.writestr("data/manifest.json", manifest)
        bundle.writestr("data/latest.json", b"[]")
        if extra:
            entry, content = extra
            bundle.writestr(zipfile.ZipInfo(entry) if isinstance(entry, str) else entry, content)
    return archive, expected


def test_preserves_verified_bytes_and_timestamp(tmp_path):
    archive, expected = payload(tmp_path)
    bridge.prepare(archive, expected, tmp_path / "site")
    assert (tmp_path / "site/data/manifest.json").read_bytes() == expected.read_bytes()
    assert (tmp_path / "site/data/latest.json").read_bytes() == b"[]"


@pytest.mark.parametrize("name", ["../outside", "/absolute", "data/../../outside", "C:/outside", "data%5coutside", "%2e%2e/outside"])
def test_rejects_zip_traversal_before_extraction(tmp_path, name):
    archive, expected = payload(tmp_path, extra=(name, "unsafe"))
    with pytest.raises(ValueError):
        bridge.prepare(archive, expected, tmp_path / "site")
    assert not (tmp_path / "site").exists()


def test_rejects_zip_symlink(tmp_path):
    entry = zipfile.ZipInfo("data/link")
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive, expected = payload(tmp_path, extra=(entry, "../outside"))
    with pytest.raises(ValueError, match="non-regular"):
        bridge.prepare(archive, expected, tmp_path / "site")


@pytest.mark.parametrize("reference", ["data/missing.json", "../outside", "https://example.com/data.json"])
def test_rejects_invalid_manifest_reference(tmp_path, reference):
    archive, expected = payload(tmp_path, files={"latestJson": reference})
    with pytest.raises(ValueError):
        bridge.prepare(archive, expected, tmp_path / "site")


def test_rejects_release_manifest_mismatch(tmp_path):
    archive, expected = payload(tmp_path)
    expected.write_bytes(b"{}")
    with pytest.raises(ValueError, match="differs"):
        bridge.prepare(archive, expected, tmp_path / "site")


def test_supports_vps_checksum_inventory(tmp_path):
    archive, expected = payload(tmp_path, files={"data/latest.json": {"sha256": hashlib.sha256(b"[]").hexdigest(), "size": 2}})
    bridge.prepare(archive, expected, tmp_path / "site")


def test_rejects_vps_checksum_mismatch(tmp_path):
    archive, expected = payload(tmp_path, files={"data/latest.json": {"sha256": "0" * 64, "size": 2}})
    with pytest.raises(ValueError, match="checksum"):
        bridge.prepare(archive, expected, tmp_path / "site")


def test_verify_retries_stale_manifest(tmp_path, monkeypatch):
    archive, expected = payload(tmp_path)
    site = tmp_path / "site"
    bridge.prepare(archive, expected, site)
    requests = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return b"{}" if len(requests) == 1 else expected.read_bytes()
    def fetch(request, timeout):
        requests.append(request)
        return Response()
    monkeypatch.setattr(bridge.urllib.request, "urlopen", fetch)
    monkeypatch.setattr(bridge.time, "sleep", lambda _: None)
    bridge.verify(site, "https://pages.example/", attempts=2)
    assert len(requests) == 2
    assert requests[0].get_header("User-agent")
    assert requests[0].get_header("Cache-control") == "no-cache"


def test_verify_fails_for_permanent_mismatch(tmp_path, monkeypatch):
    archive, expected = payload(tmp_path)
    site = tmp_path / "site"
    bridge.prepare(archive, expected, site)
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return b"{}"
    monkeypatch.setattr(bridge.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(ValueError, match="did not match"):
        bridge.verify(site, "https://pages.example/", attempts=1)
