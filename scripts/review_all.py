#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""review_all.py: standardized 3-family review + gate mark (2026-08-10 process optimization).

用法（在 VPS /root/crawl_phones 下）：
  python3 scripts/review_all.py <diff_path> --extra "背景说明"
流程：
  1. review_prompt_builder 生成标准评审 prompt（场景矩阵/反例要求/diff stat/防幻觉）
  2. 主模型 deepseek-v4-flash + 两家 sidecar（nvidia-nim + volcengine-coding）
  3. review_gate mark
"""
import argparse
import json
import os
import sys
import time
import subprocess
import datetime
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path('/root/crawl_phones')
AUTH = json.load(open('/root/.config/opencode/auth.json'))
sys.path.insert(0, '/root/.config/opencode/scripts')
import candidate_state
sys.path.insert(0, str(ROOT / 'scripts'))
from review_prompt_builder import build_prompt


def call_llm(url, key, model, prompt, max_tokens, timeout=540):
    for attempt in range(5):
        try:
            body = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                               'temperature': 0.1, 'max_tokens': max_tokens}).encode('utf-8')
            req = urllib.request.Request(url, data=body, headers={
                'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                c = json.loads(resp.read().decode('utf-8'))['choices'][0]['message'].get('content') or ''
            if c.strip() and len(c) > 50:
                return c
        except Exception as e:
            print(f'  attempt {attempt + 1} {type(e).__name__}', flush=True)
            time.sleep(30)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('diff_path')
    ap.add_argument('--extra', default='')
    ap.add_argument('--tag', default='review')
    args = ap.parse_args()

    G = candidate_state.candidate_hash(ROOT, 'staged')
    prompt = build_prompt(args.diff_path, args.extra, G)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')
    EV = str(ROOT / '.review-evidence')
    print('gate:', G)

    # 主模型
    c = call_llm('https://api.deepseek.com/chat/completions', AUTH['deepseek']['key'],
                 'deepseek-chat', prompt, 24000)
    if not c:
        print('MAIN FAILED'); return 1
    mp = f'{EV}/main-deepseek-{args.tag}-{stamp}.md'
    open(mp, 'w', encoding='utf-8').write(c)
    print('MAIN OK', len(c))

    # 两家 sidecar
    results = {}
    for name, url, key, model, fn in (
        ('nemotron', 'https://integrate.api.nvidia.com/v1/chat/completions', AUTH['nvidia']['key'],
         'nvidia/nemotron-3-ultra-550b-a55b', f'nemotron-{args.tag}-{stamp}.md'),
        ('volc', 'https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions', AUTH['volcengine-coding']['key'],
         'glm-5.2', f'volc-{args.tag}-{stamp}.md'),
    ):
        c = call_llm(url, key, model, prompt, 16000)
        if c:
            open(f'{EV}/{fn}', 'w', encoding='utf-8').write(c)
            results[name] = fn
            print(f'{name} OK', len(c))
        else:
            print(f'{name} FAILED')

    # 证据文件绑定
    NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for sid, fn in results.items():
        pid = 'nvidia-nim' if sid == 'nemotron' else 'volcengine-coding'
        mid = 'nvidia/nemotron-3-ultra-550b-a55b' if sid == 'nemotron' else 'glm-5.2'
        json.dump({'tool': 'sidecar', 'provider_id': pid, 'model_id': mid, 'session_id': sid,
                   'session_path': f'{EV}/{fn}', 'output_path': f'{EV}/{fn}',
                   'diff_sha256': G, 'reviewed_at': NOW},
                  open(f'/tmp/ev_{sid}_{args.tag}.json', 'w'), ensure_ascii=False)
    json.dump({'tool': 'hermes', 'provider_id': 'deepseek', 'model_id': 'deepseek-v4-flash',
               'session_id': f'{args.tag}-main', 'session_path': mp, 'diff_sha256': G},
              open(f'/tmp/ev_main_{args.tag}.json', 'w'), ensure_ascii=False)
    for f in ([mp] + [f'{EV}/{fn}' for fn in results.values()]):
        lines = open(f, encoding='utf-8').read().split('\n')
        if lines and lines[0].startswith('DIFF_SHA256'):
            lines[0] = 'DIFF_SHA256: ' + G
        else:
            lines.insert(0, 'DIFF_SHA256: ' + G)
        open(f, 'w', encoding='utf-8').write('\n'.join(lines))
    print('evidence written')

    # 两家 PASS 才 mark（缺一家则提示重跑）
    ok = all('结论：PASS' in open(f'{EV}/{fn}', encoding='utf-8').read() for fn in results.values())
    if len(results) < 2 or not ok:
        print('需要至少两家 PASS 评审——检查证据文件后重跑')
        return 1
    ev_args = []
    for sid in results:
        ev_args += ['--evidence', f'/tmp/ev_{sid}_{args.tag}.json']
    out = subprocess.run(
        ['python3', '/root/.config/opencode/scripts/review_gate.py', 'mark', '--repo', str(ROOT),
         '--main-model', 'deepseek/deepseek-v4-flash', '--main-evidence', f'/tmp/ev_main_{args.tag}.json'] + ev_args,
        capture_output=True, text=True)
    print(out.stdout[-150:] + out.stderr[-150:])
    return 0


if __name__ == '__main__':
    sys.exit(main())
