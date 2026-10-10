#!/usr/bin/env python3
"""Publish the already verified CNB site without rebuilding its data."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile


def site_file(site, relative):
    path = site / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts or path.is_symlink():
        raise ValueError(f'unsafe site path: {relative}')
    if not path.resolve().is_relative_to(site.resolve()) or not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f'missing/empty verified site file: {relative}')
    return path


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def collect_assets(site, repo):
    manifest_path = site_file(site, 'data/manifest.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('manifest.files must identify the verified payload')
    for key, value in files.items():
        relative = value if isinstance(value, str) else key
        path = site_file(site, relative)
        if isinstance(value, dict) and value.get('sha256') != file_hash(path):
            raise ValueError(f'manifest hash mismatch: {relative}')
    site_file(site, 'index.html')
    assets = {'manifest.json': manifest_path}
    kind = repo.split('/')[-1]
    if kind == 'crawl_vps_promotions':
        for path in sorted((site / 'data').rglob('*')):
            if path.is_file() and path.name != 'manifest.json':
                if path.name in assets:
                    raise ValueError(f'duplicate VPS asset basename: {path.name}')
                assets[path.name] = site_file(site, path.relative_to(site).as_posix())
        return assets
    latest = site_file(site, 'data/latest.json')
    if kind in ('crawl-sim', 'crawl_laptops', 'crawl_ac'):
        prefix = {'crawl-sim': 'sim', 'crawl_laptops': 'laptops', 'crawl_ac': 'ac'}[kind]
        assets[prefix + '-latest.json'] = latest
        if kind == 'crawl-sim':
            assets['sim-filtered.json'] = site_file(site, 'data/filtered.json')
    elif kind in ('crawl_cars', 'crawl_phones'):
        date = str(manifest.get('date', ''))
        if not re.fullmatch(r'\d{8}', date):
            raise ValueError('manifest.date must be YYYYMMDD')
        if kind == 'crawl_cars':
            assets[f'merged_{date}.json'] = latest
            assets[f'filtered_cars_{date}.json'] = site_file(site, 'data/filtered.json')
            assets[f'filtered_cars_{date}.csv'] = site_file(site, f'data/filtered_cars_{date}.csv')
            merged_csv = site / f'data/merged_{date}.csv'
            if merged_csv.is_file(): assets[merged_csv.name] = merged_csv
        else:
            assets[f'merged_phones_{date}.json'] = latest
            assets[f'merged_phones_{date}.csv'] = site_file(site, f'data/merged_phones_{date}.csv')
        evidence = site / 'data/merge_evidence_report.json'
        if evidence.is_file(): assets[f'merge_evidence_report_{date}.json'] = evidence
    else:
        raise ValueError(f'unsupported crawler repository: {kind}')
    return assets


def bundle_site(site, destination):
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path in sorted(site.rglob('*')):
            if path.is_symlink(): raise ValueError(f'symlink in site: {path}')
            if path.is_file():
                archive.write(path, path.relative_to(site).as_posix())


class GitHub:
    def __init__(self, repo, token):
        self.base = 'https://api.github.com/repos/' + repo
        self.headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                        'X-GitHub-Api-Version': '2026-03-10', 'User-Agent': 'cnb-verified-site-publisher'}

    def request(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={**self.headers, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=120) as response:
            raw = response.read()
        return json.loads(raw) if raw else None

    def get_release(self, tag):
        try:
            return self.request('GET', '/releases/tags/' + urllib.parse.quote(tag, safe=''))
        except urllib.error.HTTPError as error:
            if error.code == 404: return None
            raise

    def assets(self, release):
        result = []
        page = 1
        while True:
            batch = self.request('GET', f'/releases/{release["id"]}/assets?per_page=100&page={page}')
            result.extend(batch)
            if len(batch) < 100: return result
            page += 1

    def upload(self, release, name, path):
        url = release['upload_url'].split('{')[0] + '?' + urllib.parse.urlencode({'name': name})
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname != 'uploads.github.com':
            raise ValueError('unexpected GitHub upload URL')
        size = path.stat().st_size
        headers = {**self.headers, 'Content-Type': mimetypes.guess_type(name)[0] or 'application/octet-stream',
                   'Content-Length': str(size)}
        with path.open('rb') as handle:
            req = urllib.request.Request(url, data=handle, method='POST', headers=headers)
            with urllib.request.urlopen(req, timeout=600) as response:
                asset = json.loads(response.read())
        if asset.get('state') != 'uploaded' or asset.get('size') != size:
            raise RuntimeError(f'incomplete Release upload: {name}')


def publish(api, assets, tag, ref, workflow=None):
    if not re.fullmatch(r'cnb-data-[A-Za-z0-9][A-Za-z0-9._-]*', tag):
        raise ValueError('version tag must be a safe cnb-data-* build tag')
    if api.get_release(tag) is not None:
        raise ValueError('version tag already exists; use a new build tag')
    version = api.request('POST', '/releases', {'tag_name': tag, 'target_commitish': ref,
                          'name': tag, 'draft': True, 'make_latest': 'false'})
    for name, path in assets.items(): api.upload(version, name, path)
    api.request('PATCH', f'/releases/{version["id"]}', {'draft': False, 'make_latest': 'true'})
    if workflow:
        api.request('POST', '/actions/workflows/' + urllib.parse.quote(workflow, safe='') + '/dispatches',
                    {'ref': ref, 'inputs': {'release_tag': tag}})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-dir', type=Path, required=True)
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPO_SLUG') or 'Fatty911/' + Path(__file__).resolve().parents[1].name)
    parser.add_argument('--tag', default='cnb-data-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + (os.environ.get('CNB_BUILD_ID') or uuid.uuid4().hex[:12]))
    parser.add_argument('--ref', default='main')
    parser.add_argument('--workflow')
    args = parser.parse_args(argv)
    token = os.environ.get('GITHUB_PAT') or os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token: raise ValueError('missing GitHub publishing token')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo):
        raise ValueError('repo must be owner/repository')
    assets = collect_assets(args.site_dir, args.repo)
    with tempfile.TemporaryDirectory(prefix='cnb-release-') as scratch:
        archive = Path(scratch) / 'verified-site.zip'
        bundle_site(args.site_dir, archive)
        assets['verified-site.zip'] = archive
        publish(GitHub(args.repo, token), assets, args.tag, args.ref, args.workflow)
    print(f'Published verified immutable build {args.repo} {args.tag}: {", ".join(assets)}')


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f'GitHub publishing failed: HTTP {error.code} ({error.reason})') from None
    except (ValueError, RuntimeError, OSError, urllib.error.URLError) as error:
        raise SystemExit(f'GitHub publishing failed: {error}') from None
