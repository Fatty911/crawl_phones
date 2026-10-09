import os
from pathlib import Path
import subprocess
import tempfile
import yaml


def codeberg_scripts():
    data = yaml.safe_load((Path(__file__).parents[1] / '.cnb.yml').read_text(encoding='utf-8'))
    for jobs in data['main'].values():
        if isinstance(jobs, list):
            for job in jobs:
                if isinstance(job, dict):
                    for stage in job.get('stages', []):
                        if stage.get('name') == '发布到Codeberg Pages':
                            yield stage['script']


def run_stage(script, *, enabled='true', bootstrap_rc='0', health_rc='0', token='test-token'):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        for folder in ('site', 'docs'):
            (root / folder).mkdir()
            (root / folder / 'index.html').write_text('verified')
        marker = root / 'pushed.txt'
        env = dict(os.environ, CODEBERG_TOKEN=token, PROXY_TEST_ENABLED=enabled,
                   BOOTSTRAP_RC=bootstrap_rc, CODEBERG_HEALTH_RC=health_rc, PUSH_MARKER=marker.as_posix())
        script = script.replace('/tmp/codeberg-proxy.env', (root / 'proxy.env').as_posix())
        script = script.replace('/tmp/codeberg-proxy.sh', (root / 'proxy.sh').as_posix())
        script = script.replace('/tmp/cb-askpass.sh', (root / 'askpass.sh').as_posix())
        mocks = '''
        python() {
          [ "$BOOTSTRAP_RC" = 0 ] || return "$BOOTSTRAP_RC"
          target=""
          while [ "$#" -gt 0 ]; do
            if [ "$1" = --github-env ]; then shift; target="$1"; fi
            shift
          done
          printf 'PROXY_ENABLED=%s\nHTTPS_PROXY=http://127.0.0.1:7890\nHTTP_PROXY=http://127.0.0.1:7890\n' "$PROXY_TEST_ENABLED" > "$target"
        }
        git() {
          if [ "$1" = push ]; then printf '%s' "${HTTPS_PROXY:-none}" > "$PUSH_MARKER"; fi
          return 0
        }
        pkill() { return 0; }
        curl() {
          proxy=""
          while [ "$#" -gt 0 ]; do
            if [ "$1" = --proxy ]; then shift; proxy="$1"; fi
            shift
          done
          [ "$proxy" = http://127.0.0.1:7890 ] || return 99
          return "$CODEBERG_HEALTH_RC"
        }
        sleep() { return 0; }
        '''
        result = subprocess.run(['sh', '-c', mocks + script], cwd=temp, env=env,
                                capture_output=True, text=True, encoding='utf-8', timeout=20)
        return result, marker.read_text() if marker.exists() else None


def test_codeberg_push_uses_validated_proxy():
    scripts = list(codeberg_scripts())
    assert scripts
    for script in scripts:
        assert '--test-url https://codeberg.org' in script
        result, proxy = run_stage(script)
        assert result.returncode == 0, result.stderr
        assert proxy == 'http://127.0.0.1:7890'


def test_codeberg_proxy_failure_never_pushes():
    for script in codeberg_scripts():
        for args in ({'enabled': 'false'}, {'bootstrap_rc': '7'}, {'health_rc': '22'}):
            result, proxy = run_stage(script, **args)
            assert result.returncode != 0
            assert proxy is None


def test_codeberg_missing_token_remains_hard_failure():
    for script in codeberg_scripts():
        result, proxy = run_stage(script, token='')
        assert result.returncode != 0
        assert proxy is None
