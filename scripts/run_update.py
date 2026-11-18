# -*- coding: utf-8 -*-
"""唯一更新入口：跑一次完整决策，刷新 web/index.html 与 analysis_packet.json。

用法:
  python3 scripts/run_update.py                # 实时取数（默认），失败自动降级
  python3 scripts/run_update.py --strict       # 非 OK 状态（降级/弃权/演示）退出码 1
  python3 scripts/run_update.py --snapshot     # 完全不联网，用离线快照（仅演示）
  python3 scripts/run_update.py --json         # 机器可读输出（供 agent / workflow 解析）
  python3 scripts/run_update.py --push         # 生成后提交并推送（用本机 IP 取数）
  python3 scripts/run_update.py --verify       # 只做发布前校验（不重新取数）

退出码: 0 正常 · 1 strict 下状态非 OK · 2 运行异常 · 3 推送失败 · 4 校验失败
"""
import os
import sys
import json
import argparse
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))
from etfquant import config, packet, pipeline  # noqa: E402

PRODUCTS = ['web/index.html', 'web/analysis_packet.json', 'data/last_run.json']
# 持仓分析产物：只有本地跑过 analyze_positions.py 才存在，存在才纳入同一次提交
OPTIONAL_PRODUCTS = ['docs/持仓分析报告.md', 'data/packets/positions_packet.json']


def git_push(r):
    """提交并推送产物。只 add 指定产物文件，绝不动其他改动。"""
    def run(*args):
        return subprocess.run(args, cwd=config.ROOT, capture_output=True, text=True)

    if not run('git', 'remote').stdout.strip():
        print('未配置 git remote，跳过推送。', file=sys.stderr)
        return 3
    extra = [p for p in OPTIONAL_PRODUCTS if os.path.exists(os.path.join(config.ROOT, p))]
    run('git', 'add', *PRODUCTS, *extra)
    if run('git', 'diff', '--cached', '--quiet').returncode == 0:
        print('产物与上次一致，跳过提交')
        return 0
    msg = 'chore: 更新 %s（%s · %s）' % (r['data_date'] or '—', r['status'],
                                        '实时' if not r['degraded'] else '降级')
    c = run('git', 'commit', '-m', msg)
    if c.returncode != 0 and 'identity' in (c.stderr or c.stdout).lower():
        # 本地没配 author 时临时注入身份，不改动任何 git 配置
        c = run('git', '-c', 'user.name=etfquant-bot',
                '-c', 'user.email=etfquant-bot@users.noreply.github.com',
                'commit', '-m', msg)
    if c.returncode != 0:
        print('提交失败：%s' % (c.stderr or c.stdout).strip(), file=sys.stderr)
        return 3
    p = run('git', 'push')
    if p.returncode != 0:
        # 生成期间远端被每日流水线推进过：拉一次再推。
        # -X ours 表示冲突时保留远端版本 —— 远端也是同一流程生成的产物，
        # 取哪份数据等价；这样产物冲突不会把仓库留在 rebase 中间态。
        print('推送被拒，拉取远端后重试')
        run('git', 'fetch', 'origin', 'main')
        rb = run('git', 'rebase', '-X', 'ours', 'origin/main')
        if rb.returncode != 0:
            run('git', 'rebase', '--abort')
            print('与远端产物冲突且无法自动合并：%s'
                  % (rb.stderr or rb.stdout).strip(), file=sys.stderr)
            return 3
        p = run('git', 'push')
    if p.returncode != 0:
        print('推送失败：%s' % (p.stderr or p.stdout).strip(), file=sys.stderr)
        return 3
    print('已推送：%s' % msg)
    return 0


def write_manifest(r):
    """data/last_run.json：给 agent / 监控判断「今天有没有跑成功、数据是哪天、什么状态」。"""
    path = os.path.join(config.ROOT, 'data', 'last_run.json')
    config.ensure_dirs(os.path.dirname(path))
    payload = {
        'ok': r['status'] in ('OK', 'DEGRADED'),
        'status': r['status'],
        'ran_at': pipeline.now_tz().strftime('%Y-%m-%d %H:%M:%S'),
        'mode': r.get('mode', 'live'),
        'data_date': r['data_date'],
        'degraded': r['degraded'], 'synthetic': r.get('synthetic', False),
        'levels': r['levels'], 'level_count': r['level_count'],
        'action_count': r['action_count'],
        'orders': r['orders'],
        'skipped': r['skipped'],
        'fallback': r['source']['fallback'],
        'validation': r.get('validation'),
        'run_id': r.get('run_id'),
        'input_hash': r.get('input_hash'),
        'config_hash': r.get('config_hash'),
        'html': r['html'],
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def verify_products():
    """校验页面、数据包与运行清单来自同一次运行，并复跑数据包不变量。"""
    root = config.ROOT
    paths = dict(packet=os.path.join(root, 'web', 'analysis_packet.json'),
                 manifest=os.path.join(root, 'data', 'last_run.json'),
                 html=os.path.join(root, 'web', 'index.html'))
    errors, warnings = [], []
    for name, path in paths.items():
        if not os.path.exists(path):
            errors.append('缺少发布产物：%s' % name)
    if errors:
        return dict(ok=False, errors=errors, warnings=warnings)

    pkt = json.load(open(paths['packet'], encoding='utf-8'))
    man = json.load(open(paths['manifest'], encoding='utf-8'))
    with open(paths['html'], encoding='utf-8') as f:
        html = f.read()

    import re
    m = re.search(r'"packet":\{[^}]*"run_id":"([^"]+)"', html)
    html_run = m.group(1) if m else None
    ids = dict(packet=pkt.get('run_id'), manifest=man.get('run_id'), html=html_run)
    values = {v for v in ids.values() if v}
    if len(values) > 1:
        errors.append('产物不同源：run_id 不一致 %s' % ids)
    if man.get('input_hash') and pkt.get('input_hash') \
            and man['input_hash'] != pkt['input_hash']:
        errors.append('运行清单与数据包 input_hash 不一致')
    chk = packet.validate_packet(pkt, cfg=config.cfg())
    errors.extend(chk['errors'])
    warnings.extend(chk['warnings'])
    if not man.get('ok'):
        warnings.append('最近一次运行状态为 %s' % man.get('status'))
    return dict(ok=not errors, errors=errors, warnings=warnings,
                run_id=ids.get('packet'), ids=ids)


def main():
    ap = argparse.ArgumentParser(description='ETF 决策平台 · 单次更新')
    ap.add_argument('--snapshot', action='store_true', help='不联网，用离线快照（仅演示）')
    ap.add_argument('--strict', action='store_true',
                    help='状态非 OK 时退出码 1（供 CI 使用）')
    ap.add_argument('--json', action='store_true', help='输出机器可读 JSON')
    ap.add_argument('--push', action='store_true', help='生成后 commit + push 产物')
    ap.add_argument('--verify', action='store_true', help='只校验已生成的 analysis_packet')
    a = ap.parse_args()

    if a.verify:
        chk = verify_products()
        print(json.dumps(chk, ensure_ascii=False, indent=2))
        return 0 if chk['ok'] else 4

    try:
        r = pipeline.run(use_live=not a.snapshot)
    except Exception as e:
        if a.json:
            print(json.dumps({'ok': False, 'status': 'ERROR', 'error': str(e)},
                             ensure_ascii=False))
        else:
            print('运行失败：%s' % e)
        return 2

    manifest = write_manifest(r)

    if a.json:
        slim = {k: v for k, v in r.items() if k not in ('source',)}
        slim['source'] = {k: r['source'][k] for k in
                          ('live', 'degraded', 'synthetic', 'premium_ok', 'fallback')}
        print(json.dumps(slim, ensure_ascii=False))
    else:
        print('已生成 %s（%.1f KB）' % (r['html'], r['html_bytes'] / 1024))
        print('状态 %s · 数据日 %s · 来源 %s · 标的 %s 只 · 动作 %s'
              % (r['status'], r['data_date'] or '—',
                 '实时' if not r['degraded'] else '降级',
                 r['levels'], r['action_count']))
        if r['skipped']:
            print('已跳过（缺行情）：%s' % '、'.join(r['skipped']))
        if r['source']['fallback']:
            print('降级明细：')
            for x in r['source']['fallback']:
                print('  - %s' % x)
        print('清单：%s' % manifest)

    if not r['validation']['ok']:
        print('发布前校验未通过：%s' % '；'.join(r['validation']['errors']),
              file=sys.stderr)
        return 4

    if a.push:
        code = git_push(r)
        if code:
            return code

    if a.strict and r['status'] != 'OK':
        print('strict：状态 %s（非 OK），按失败处理' % r['status'], file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
