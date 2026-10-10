import contextlib
import gzip
import importlib.util
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('proxy_runtime_auth',ROOT/'scripts/setup_proxy_runtime.py')
proxy=importlib.util.module_from_spec(spec);spec.loader.exec_module(proxy)

def test_mihomo_api_auth_does_not_reach_asset_download(tmp_path):
    release={'assets':[{'name':'mihomo-linux-amd64-v1.19.0.gz','browser_download_url':'https://github.com/MetaCubeX/mihomo/releases/download/v1.19.0/mihomo-linux-amd64-v1.19.0.gz'}]}
    opener=Mock();opener.open.return_value=io.BytesIO(json.dumps(release).encode())
    with patch.dict(os.environ,{'GITHUB_TOKEN':'fixture-token'}),patch.object(proxy.urllib.request,'build_opener',return_value=opener),patch.object(proxy.urllib.request,'urlopen',return_value=io.BytesIO(gzip.compress(b'fixture-binary'))) as download:
        binary=proxy.download_mihomo(tmp_path)
    assert binary.read_bytes()==b'fixture-binary'
    api_request=opener.open.call_args.args[0]
    assert api_request.get_header('Authorization')=='Bearer fixture-token'
    assert download.call_args.args[0].get_header('Authorization') is None

def test_cnb_mask_does_not_emit_plaintext_secret():
    output=io.StringIO()
    with patch.dict(os.environ,{'GITHUB_ACTIONS':'false'}),contextlib.redirect_stdout(output):proxy.mask('fixture-secret')
    assert 'fixture-secret' not in output.getvalue()

def test_github_mask_protocol_keeps_platform_compatibility():
    output=io.StringIO()
    with patch.dict(os.environ,{'GITHUB_ACTIONS':'true'}),contextlib.redirect_stdout(output):proxy.mask('fixture-secret')
    assert output.getvalue()=='::add-mask::fixture-secret\n'
