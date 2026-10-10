import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('release_publisher', Path(__file__).parents[1] / 'scripts/publish_github_release.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class ReleasePublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.site = Path(self.temp.name) / 'site'
        (self.site / 'data').mkdir(parents=True)
        (self.site / 'index.html').write_text('<html>verified</html>')
        for name in ('latest.json', 'filtered.json', 'deals.json'):
            (self.site / 'data' / name).write_text('[{"id":1}]')
        self.manifest({'date': '20261009', 'files': {'latestJson': 'data/latest.json'}})

    def manifest(self, value):
        (self.site / 'data/manifest.json').write_text(json.dumps(value))

    def test_all_repository_contracts_preserve_verified_bytes(self):
        for repo, expected in [('crawl-sim', 'sim-latest.json'), ('crawl_laptops', 'laptops-latest.json'), ('crawl_ac', 'ac-latest.json'), ('crawl_phones', 'merged_phones_20261009.json'), ('crawl_cars', 'merged_20261009.json'), ('crawl_vps_promotions', 'deals.json')]:
            for name in ('merged_phones_20261009.csv', 'filtered_cars_20261009.csv'):
                (self.site / 'data' / name).write_text('id\n1\n')
            assets = publisher.collect_assets(self.site, 'Fatty911/' + repo)
            self.assertEqual(assets[expected].read_bytes(), (self.site / 'data' / ('deals.json' if repo == 'crawl_vps_promotions' else 'latest.json')).read_bytes())

    def test_missing_manifest_or_payload_fails(self):
        (self.site / 'data/latest.json').unlink()
        with self.assertRaises(ValueError):
            publisher.collect_assets(self.site, 'Fatty911/crawl-sim')

    def test_manifest_path_escape_fails(self):
        self.manifest({'files': {'latestJson': '../outside.json'}})
        with self.assertRaises(ValueError):
            publisher.collect_assets(self.site, 'Fatty911/crawl-sim')

    def test_zip_root_and_manifest_bytes_match(self):
        archive = Path(self.temp.name) / 'verified-site.zip'
        publisher.bundle_site(self.site, archive)
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(z.read('data/manifest.json'), (self.site / 'data/manifest.json').read_bytes())
            self.assertIn('index.html', z.namelist())

    def test_upload_streams_file_and_checks_response(self):
        path = self.site / 'data/latest.json'
        requests = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps({'state': 'uploaded', 'size': path.stat().st_size}).encode()
        def opened(req, **kwargs):
            requests.append(req)
            self.assertTrue(hasattr(req.data, 'read'))
            self.assertEqual(req.data.read(), path.read_bytes())
            return Response()
        with patch.object(publisher.urllib.request, 'urlopen', opened):
            publisher.GitHub('Fatty911/crawl-sim', 'test').upload({'upload_url': 'https://uploads.github.com/test{?name,label}'}, 'sim-latest.json', path)
        self.assertEqual(requests[0].get_header('Content-length'), str(path.stat().st_size))

    def fake_api(self, fail_version=False):
        events = []
        class Fake:
            def get_release(self, tag):
                events.append(('get', tag))
                return {'id': 2, 'assets': [{'id': 9, 'name': 'manifest.json'}]} if tag == 'data-latest' else None
            def request(self, method, path, body=None):
                events.append((method, path))
                if path.endswith('/dispatches'): self.dispatch_body = body
                if method == 'DELETE': raise RuntimeError('immutable asset cannot be deleted')
                return {'id': 1, 'assets': []}
            def upload(self, release, name, path):
                events.append(('upload', release['id'], name))
                if fail_version: raise RuntimeError('upload failed')
            def assets(self, release): return release['assets']
        return Fake(), events

    def test_immutable_version_dispatches_exact_tag_without_stable_mutation(self):
        api, events = self.fake_api()
        publisher.publish(api, {'manifest.json': self.site / 'data/manifest.json'}, 'cnb-data-test', 'main', 'cnb-pages.yml')
        self.assertNotIn(('get', 'data-latest'), events)
        self.assertLess(events.index(('upload', 1, 'manifest.json')), events.index(('PATCH', '/releases/1')))
        self.assertEqual(events[-1], ('POST', '/actions/workflows/cnb-pages.yml/dispatches'))
        self.assertEqual(api.dispatch_body, {'ref': 'main', 'inputs': {'release_tag': 'cnb-data-test'}})

    def test_version_failure_never_touches_stable(self):
        api, events = self.fake_api(True)
        with self.assertRaises(RuntimeError):
            publisher.publish(api, {'manifest.json': self.site / 'data/manifest.json'}, 'cnb-data-test', 'main', 'cnb-pages.yml')
        self.assertNotIn(('get', 'data-latest'), events)

    def test_missing_token_fails_before_network(self):
        with patch.dict(publisher.os.environ, {}, clear=True), patch.object(publisher.urllib.request, 'urlopen') as opened:
            with self.assertRaises(ValueError): publisher.main(['--site-dir', str(self.site), '--repo', 'Fatty911/crawl-sim'])
            opened.assert_not_called()

    def test_publish_failure_does_not_dispatch(self):
        api, events = self.fake_api()
        original = api.request
        def request(method, path, body=None):
            if method == 'PATCH': raise RuntimeError('publish failed')
            return original(method, path, body)
        api.request = request
        with self.assertRaises(RuntimeError):
            publisher.publish(api, {'manifest.json': self.site / 'data/manifest.json'}, 'cnb-data-test', 'main', 'cnb-pages.yml')
        self.assertNotIn(('POST', '/actions/workflows/cnb-pages.yml/dispatches'), events)

    def test_vps_manifest_hash_is_enforced(self):
        self.manifest({'files': {'data/deals.json': {'sha256': 'incorrect'}}})
        with self.assertRaises(ValueError): publisher.collect_assets(self.site, 'Fatty911/crawl_vps_promotions')

    def test_vps_optional_deals_need_not_exist(self):
        (self.site / 'data/deals.json').unlink()
        assets = publisher.collect_assets(self.site, 'Fatty911/crawl_vps_promotions')
        self.assertIn('manifest.json', assets)
        self.assertNotIn('deals.json', assets)

    def test_http_errors_fail_hard_except_missing_release(self):
        api = publisher.GitHub('Fatty911/crawl-sim', 'test')
        for code in (401, 403, 422, 500):
            error = publisher.urllib.error.HTTPError('https://api.github.com/', code, 'failure', {}, None)
            with patch.object(api, 'request', side_effect=error):
                with self.assertRaises(publisher.urllib.error.HTTPError): api.get_release('data-latest')
            error.close()
        missing = publisher.urllib.error.HTTPError('https://api.github.com/', 404, 'missing', {}, None)
        with patch.object(api, 'request', side_effect=missing):
            self.assertIsNone(api.get_release('data-latest'))
        missing.close()


if __name__ == '__main__':
    unittest.main()
