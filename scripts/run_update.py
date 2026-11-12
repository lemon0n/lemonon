# -*- coding: utf-8 -*-
"""唯一更新入口：跑一次完整决策，刷新 web/index.html，并可写入运行清单。

用法:
  python3 scripts/run_update.py                # 实时取数（默认），失败自动降级
  python3 scripts/run_update.py --strict       # 任一关键通道降级则退出码 1（给 CI 用）
  python3 scripts/run_update.py --snapshot     # 完全不联网，用离线快照（本地演示/测试）
  python3 scripts/run_update.py --json         # 机器可读输出（供 agent / workflow 解析）
  python3 scripts/run_update.py --push         # 生成后提交并推送到 GitHub（用本机 IP 取数）

为什么需要 --push：东财等免费接口对数据中心 IP（GitHub Actions）限流更凶，
本机家宽/办公网 IP 通常能直连。想在盘后拿最新数据又不想等 CI，就本地跑这一条，
生成与推送一次完成；CI 的定时任务继续作为兜底。

退出码: 0 正常 · 1 strict 下关键通道降级 · 2 运行异常 · 3 推送失败
"""
import os
import sys
import json
import argparse
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))
from etfquant import config, pipeline  # noqa: E402


def git_push(r):
    """提交并推送产物。只 add 两个产物文件，绝不动其他改动。"""
    def run(*args):
        return subprocess.run(args, cwd=config.ROOT, capture_output=True, text=True)

    if not run('git', 'remote').stdout.strip():
        print('未配置 git remote，跳过推送。先执行：\n'
              '  git remote add origin https://github.com/<用户>/<仓库>.git', file=sys.stderr)
        return 3
    run('git', 'add', 'web/index.html', 'data/last_run.json')
    if run('git', 'diff', '--cached', '--quiet').returncode == 0:
        print('产物与上次一致，跳过提交')
        return 0
    msg = 'chore: 更新 %s（%s）' % (r['data_date'] or '—',
                                    '实时' if not r['degraded'] else '降级')
    c = run('git', 'commit', '-m', msg)
    if c.returncode != 0:
        print('提交失败：%s' % (c.stderr or c.stdout).strip(), file=sys.stderr)
        return 3
    p = run('git', 'push')
    if p.returncode != 0:
        print('推送失败：%s' % (p.stderr or p.stdout).strip(), file=sys.stderr)
        return 3
    print('已推送：%s' % msg)
    return 0


def write_manifest(r):
    """写 data/last_run.json：给 agent / 监控判断「今天有没有跑成功、跑的是哪天的数据」。"""
    path = os.path.join(config.ROOT, 'data', 'last_run.json')
    config.ensure_dirs(os.path.dirname(path))
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    return path


def main():
    ap = argparse.ArgumentParser(description='ETF 决策平台 · 单次更新')
    ap.add_argument('--snapshot', action='store_true', help='不联网，用离线快照')
    ap.add_argument('--strict', action='store_true',
                    help='关键通道降级或数据日期非今日时退出码 1（供 CI 使用）')
    ap.add_argument('--json', action='store_true', help='输出机器可读 JSON')
    ap.add_argument('--push', action='store_true',
                    help='生成后 commit + push web/index.html 与 data/last_run.json')
    a = ap.parse_args()

    try:
        r = pipeline.run(use_live=not a.snapshot)
    except Exception as e:
        if a.json:
            print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False))
        else:
            print('运行失败：%s' % e)
        return 2

    manifest = write_manifest({
        # CI 跑在 UTC，时间必须按配置时区写，否则清单里的 ran_at 会差 8 小时
        'ok': True, 'ran_at': pipeline.now_tz().strftime('%Y-%m-%d %H:%M:%S'),
        'mode': 'snapshot' if a.snapshot else 'live',
        'data_date': r['data_date'], 'degraded': r['degraded'],
        'levels': r['levels'], 'level_count': r['level_count'],
        'orders': r['orders'], 'orders_valid': r['orders_valid'],
        'skipped': r['skipped'],
        'fallback': r['source']['fallback'], 'html': r['html'],
    })

    if a.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        print('已生成 %s（%.1f KB）' % (r['html'], r['html_bytes'] / 1024))
        print('数据日期 %s · 来源 %s · 标的 %s 只 · 分诊 %s · 参考价位 %s/%s'
              % (r['data_date'] or '—',
                 '实时' if not r['degraded'] else '降级',
                 r['levels'], r['level_count'],
                 r['orders_valid'], r['orders']))
        if r['skipped']:
            print('已跳过（缺行情）：%s' % '、'.join(r['skipped']))
        if r['source']['fallback']:
            print('降级明细：')
            for x in r['source']['fallback']:
                print('  - %s' % x)
        print('清单：%s' % manifest)

    if a.push:
        code = git_push(r)
        if code:
            return code

    if a.strict and r['degraded']:
        print('strict：关键通道降级，按失败处理', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
