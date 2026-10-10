#!/usr/bin/env python3
"""Resolve and download a complete published CNB build, with legacy fallback."""
import argparse
import fnmatch
import hashlib
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request

try:
    from scripts.publish_github_release import GitHub
except ModuleNotFoundError:
    from publish_github_release import GitHub


def valid_tag(tag):
    return isinstance(tag, str) and re.fullmatch(r'cnb-data-[A-Za-z0-9][A-Za-z0-9._-]*', tag) is not None


def uploaded_assets(release):
    return {asset['name']: asset for asset in release.get('assets', [])
            if asset.get('state') == 'uploaded' and isinstance(asset.get('size'), int) and asset['size'] > 0}


def complete_release(release):
    return (not release.get('draft') and not release.get('prerelease') and valid_tag(release.get('tag_name'))
            and {'manifest.json', 'verified-site.zip'} <= uploaded_assets(release).keys())


def select_release(api, tag=None, *, allow_legacy=True):
    if tag:
        if not valid_tag(tag): raise ValueError('release_tag must identify a cnb-data-* build')
        release = api.get_release(tag)
        if release is None or release.get('tag_name') != tag or not complete_release(release):
            raise ValueError('requested CNB Release is missing, draft, or incomplete')
        return release
    candidates = []
    page = 1
    while True:
        batch = api.request('GET', f'/releases?per_page=100&page={page}')
        candidates.extend(release for release in batch if complete_release(release))
        if len(batch) < 100: break
        page += 1
    if candidates:
        return max(candidates, key=lambda release: (release.get('published_at') or '', release['tag_name']))
    if allow_legacy:
        legacy = api.get_release('data-latest')
        if legacy is not None and not legacy.get('draft') and not legacy.get('prerelease'):
            return legacy
    raise ValueError('no complete published CNB build or legacy data-latest Release')


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        redirected = super().redirect_request(request, fp, code, message, headers, new_url)
        if redirected is not None and urllib.parse.urlsplit(request.full_url).netloc != urllib.parse.urlsplit(new_url).netloc:
            redirected.remove_header('Authorization')
        return redirected


def download_assets(api, release, patterns, destination):
    assets = uploaded_assets(release)
    selected = {}
    for pattern in patterns:
        matched = {name: asset for name, asset in assets.items() if fnmatch.fnmatchcase(name, pattern)}
        if not matched: raise ValueError(f'Release {release["tag_name"]} lacks required asset pattern: {pattern}')
        selected.update(matched)
    destination.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(SafeRedirect())
    for name, asset in selected.items():
        if '/' in name or '\\' in name or name in ('.', '..'): raise ValueError('unsafe Release asset filename')
        asset_id = asset.get('id')
        if not isinstance(asset_id, int) or asset_id <= 0: raise ValueError('invalid Release asset ID')
        request = urllib.request.Request(api.base + f'/releases/assets/{asset_id}',
                                         headers={**api.headers, 'Accept': 'application/octet-stream'})
        target = destination / name
        partial = destination / (name + '.partial')
        digest = hashlib.sha256()
        count = 0
        try:
            with opener.open(request, timeout=600) as response, partial.open('wb') as handle:
                while block := response.read(1024 * 1024):
                    handle.write(block)
                    digest.update(block)
                    count += len(block)
            if count != asset['size']: raise ValueError(f'truncated Release asset: {name}')
            expected = asset.get('digest')
            if expected and expected != 'sha256:' + digest.hexdigest():
                raise ValueError(f'Release asset digest mismatch: {name}')
            partial.replace(target)
        finally:
            if partial.exists(): partial.unlink()
    (destination / 'selected-release.txt').write_text(release['tag_name'] + '\n', encoding='utf-8')
    return list(selected)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default=os.getenv('GITHUB_REPOSITORY') or os.getenv('GITHUB_REPO_SLUG'))
    parser.add_argument('--tag', default='')
    parser.add_argument('--pattern', action='append')
    parser.add_argument('--dir', type=Path)
    parser.add_argument('--print-tag', action='store_true')
    parser.add_argument('--no-legacy', action='store_true')
    args = parser.parse_args(argv)
    if not args.repo or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo):
        raise ValueError('repo must be owner/repository')
    api = GitHub(args.repo, os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN') or os.getenv('GITHUB_PAT') or '')
    if not any(os.getenv(name) for name in ('GH_TOKEN', 'GITHUB_TOKEN', 'GITHUB_PAT')):
        api.headers.pop('Authorization')
    release = select_release(api, args.tag, allow_legacy=not args.no_legacy)
    if args.print_tag:
        print(release['tag_name'])
        return
    if args.dir is None: raise ValueError('--dir is required for downloading')
    patterns = args.pattern or ['manifest.json', 'verified-site.zip']
    downloaded = download_assets(api, release, patterns, args.dir)
    print(f'Downloaded verified Release {release["tag_name"]}: {", ".join(downloaded)}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError) as error:
        raise SystemExit(f'Verified Release download failed: {error}') from None
