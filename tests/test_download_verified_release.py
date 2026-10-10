import importlib.util
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('download_verified_release', Path(__file__).parents[1] / 'scripts/download_verified_release.py')
downloader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(downloader)


def release(tag, date='2026-10-10T00:00:00Z', *, draft=False, complete=True):
    return {'tag_name': tag, 'published_at': date, 'draft': draft, 'assets':
            [{'name': name, 'state': 'uploaded', 'size': 12} for name in
             (['manifest.json', 'verified-site.zip'] if complete else ['manifest.json'])]}


class VerifiedReleaseTests(unittest.TestCase):
    def test_newest_complete_cnb_build_wins_over_manual_legacy_and_drafts(self):
        old = release('cnb-data-old', '2026-10-09T00:00:00Z')
        newest = release('cnb-data-new')
        api = Mock()
        api.request.return_value = [release('manual-latest'), release('data-latest'),
                                    release('cnb-data-partial', complete=False),
                                    release('cnb-data-draft', draft=True), old, newest]
        self.assertIs(downloader.select_release(api), newest)
        api.get_release.assert_not_called()

    def test_pagination_selects_by_publication_time(self):
        newest = release('cnb-data-new', '2026-10-11T00:00:00Z')
        api = Mock()
        api.request.side_effect = [[release('manual')] * 100, [newest]]
        self.assertIs(downloader.select_release(api), newest)
        self.assertEqual(api.request.call_count, 2)

    def test_exact_tag_never_falls_back(self):
        api = Mock()
        for value in (None, release('cnb-data-missing', draft=True), release('cnb-data-missing', complete=False)):
            api.get_release.return_value = value
            with self.assertRaises(ValueError): downloader.select_release(api, 'cnb-data-missing')
        api.request.assert_not_called()

    def test_untrusted_tag_rejected_before_network(self):
        api = Mock()
        for tag in ('data-latest', '../cnb-data-x', 'cnb-data-a/../../x', 'cnb-data-$(echo x)'):
            with self.assertRaises(ValueError): downloader.select_release(api, tag)
        api.get_release.assert_not_called()

    def test_legacy_fallback_only_without_complete_cnb_build(self):
        api = Mock()
        api.request.return_value = []
        legacy = release('data-latest')
        api.get_release.return_value = legacy
        self.assertIs(downloader.select_release(api), legacy)
        with self.assertRaises(ValueError): downloader.select_release(api, allow_legacy=False)


    def test_streaming_download_checks_size_and_hash(self):
        body = b'verified payload'
        class Response(io.BytesIO):
            def read(self, size=-1):
                if size <= 0: raise AssertionError('download must use bounded reads')
                return super().read(size)
        value = {'tag_name': 'cnb-data-test', 'assets': [{'name': 'manifest.json', 'id': 1,
                 'state': 'uploaded', 'size': len(body), 'digest': 'sha256:' + hashlib.sha256(body).hexdigest()}]}
        api = Mock(base='https://api.github.com/repos/Fatty911/test', headers={})
        with tempfile.TemporaryDirectory() as temp, patch.object(downloader.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = Response(body)
            downloader.download_assets(api, value, ['manifest.json'], Path(temp))
            self.assertEqual((Path(temp) / 'manifest.json').read_bytes(), body)
            self.assertEqual((Path(temp) / 'selected-release.txt').read_text().strip(), 'cnb-data-test')

    def test_truncated_download_does_not_replace_previous_payload(self):
        value = {'tag_name': 'cnb-data-test', 'assets': [{'name': 'manifest.json', 'id': 1,
                 'state': 'uploaded', 'size': 100}]}
        api = Mock(base='https://api.github.com/repos/Fatty911/test', headers={})
        with tempfile.TemporaryDirectory() as temp, patch.object(downloader.urllib.request, 'build_opener') as build:
            target = Path(temp) / 'manifest.json'
            target.write_bytes(b'previous')
            build.return_value.open.return_value = io.BytesIO(b'short')
            with self.assertRaises(ValueError): downloader.download_assets(api, value, ['manifest.json'], Path(temp))
            self.assertEqual(target.read_bytes(), b'previous')
            self.assertFalse((Path(temp) / 'manifest.json.partial').exists())

    def test_redirect_does_not_forward_token_to_asset_host(self):
        request = downloader.urllib.request.Request('https://api.github.com/repos/test', headers={'Authorization': 'Bearer secret'})
        redirected = downloader.SafeRedirect().redirect_request(request, None, 302, 'Found', {}, 'https://release-assets.githubusercontent.com/payload')
        self.assertIsNone(redirected.get_header('Authorization'))


if __name__ == '__main__':
    unittest.main()
