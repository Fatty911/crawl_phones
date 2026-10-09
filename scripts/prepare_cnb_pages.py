"""Deploy the verified CNB archive without rebuilding or rewriting its payload."""
import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import time
import urllib.parse
import urllib.request
import zipfile


def safe_path(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"invalid relative path: {value!r}")
    parsed = urllib.parse.urlsplit(value)
    decoded = urllib.parse.unquote(parsed.path)
    path = PurePosixPath(decoded)
    if parsed.scheme or parsed.netloc or path.is_absolute() or ":" in decoded:
        raise ValueError(f"non-local path: {value!r}")
    if "\\" in decoded or ".." in path.parts or not path.parts:
        raise ValueError(f"path traversal: {value!r}")
    return path


def file_references(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from file_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from file_references(child)
    else:
        raise ValueError("manifest files must contain relative path strings")


def prepare(archive, expected_manifest, site):
    site = Path(site)
    if site.exists():
        raise ValueError(f"destination must not exist: {site}")
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        seen = set()
        for entry in members:
            path = safe_path(entry.filename)
            mode = entry.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError(f"non-regular ZIP member: {entry.filename}")
            if path in seen:
                raise ValueError(f"duplicate ZIP member: {entry.filename}")
            seen.add(path)
        site.mkdir(parents=True)
        for entry in members:
            target = site.joinpath(*safe_path(entry.filename).parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, target.open("xb") as destination:
                    shutil.copyfileobj(source, destination)
    staged = site / "data" / "manifest.json"
    if staged.read_bytes() != Path(expected_manifest).read_bytes():
        raise ValueError("archive manifest differs from Release manifest asset")
    manifest = json.loads(staged.read_bytes())
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    if not (site / "index.html").is_file():
        raise ValueError("site index.html is missing")
    files = manifest.get("files", {})
    inventory = isinstance(files, dict) and bool(files) and all(
        isinstance(metadata, dict) and "sha256" in metadata
        for metadata in files.values()
    )
    references = list(files) if inventory else list(file_references(files))
    if not references and not any(path.name != "manifest.json" for path in (site / "data").glob("*.json")):
        raise ValueError("manifest has no data files")
    for reference in references:
        target = site.joinpath(*safe_path(reference).parts)
        if not target.is_file():
            raise ValueError(f"manifest references missing file: {reference}")
        if inventory:
            import hashlib
            if hashlib.sha256(target.read_bytes()).hexdigest() != files[reference]["sha256"]:
                raise ValueError(f"manifest checksum mismatch: {reference}")
    print(f"verified CNB site: {len(members)} archive members, {len(references)} references")


def verify(site, page_url, attempts=12, interval=10):
    expected = (Path(site) / "data" / "manifest.json").read_bytes()
    url = urllib.parse.urljoin(page_url.rstrip("/") + "/", "data/manifest.json")
    for attempt in range(1, attempts + 1):
        separator = "&" if "?" in url else "?"
        request = urllib.request.Request(
            url + separator + urllib.parse.urlencode({"cnb_verify": time.time_ns()}),
            headers={"User-Agent": "Mozilla/5.0 CNB-Pages-Verification",
                     "Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                actual = response.read()
            if actual == expected:
                print("deployed manifest matches verified CNB payload byte-for-byte")
                return
            print(f"manifest mismatch on attempt {attempt}/{attempts}")
        except Exception as exc:
            print(f"manifest readback attempt {attempt}/{attempts}: {exc}")
        if attempt < attempts:
            time.sleep(interval)
    raise ValueError("deployed manifest did not match verified CNB payload")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True)
    parser.add_argument("--archive")
    parser.add_argument("--manifest")
    parser.add_argument("--verify-url")
    args = parser.parse_args()
    if args.verify_url:
        verify(args.site, args.verify_url)
    elif args.archive and args.manifest:
        prepare(args.archive, args.manifest, args.site)
    else:
        parser.error("provide --archive and --manifest, or --verify-url")


if __name__ == "__main__":
    main()
