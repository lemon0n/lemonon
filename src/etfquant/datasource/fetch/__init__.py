# -*- coding: utf-8 -*-
"""数据抓取统一入口：市场快照 / 宽基份额 / 行业权重。

三个任务各自独立、互不阻断：任一抓取失败都保留上次快照，让主流程继续。
每日只跑 market + national；行业权重变化慢，需要时手动 --sector。
"""
from __future__ import annotations

import argparse
import sys
import time

from . import market, national, news, sector

TASKS = {
    'market': market.main,
    'national': national.main,
    'sector': sector.main,
    'news': news.main,
}
LABELS = {
    'market': '市场实时数据（广度/分布/外盘/折溢价）',
    'national': '宽基 ETF 份额（国家队动向）',
    'sector': '指数 → 行业权重',
    'news': '财经快讯（实时）',
}


def run(names=None, argv=None) -> dict:
    """按顺序执行任务；返回 {'task': {'ok', 'seconds', 'error'}}。

    argv 支持两种形式：单个列表（所有任务共用）或 {任务名: [参数]} 映射。
    编排入口用映射把参数只发给对应任务，避免 --weeks 之类被透传给不认识它的子命令。
    """
    names = list(names or ('market', 'national', 'news'))
    argvs = argv if isinstance(argv, dict) else {n: argv for n in names}
    results = {}
    for name in names:
        fn = TASKS.get(name)
        if fn is None:
            results[name] = dict(ok=False, seconds=0.0, error='未知任务：%s' % name)
            continue
        sub_argv = list(argvs.get(name) or [])
        started = time.monotonic()
        try:
            code = fn() if name in ('market', 'news') else fn(sub_argv)
            ok = code in (0, None)
            error = None if ok else '退出码 %s' % code
        except SystemExit as exc:                   # 参数解析中断等：记为失败，不拖垮其它任务
            ok, error = False, 'SystemExit: %s' % (exc.code,)
        except Exception as exc:                    # 抓取失败不得中断主流程
            ok, error = False, '%s: %s' % (type(exc).__name__, exc)
        results[name] = dict(ok=ok, seconds=round(time.monotonic() - started, 1),
                             error=error)
        if not ok:
            print('[警告] %s 未完成：%s（本次不使用旧值）' % (LABELS[name], error),
                  file=sys.stderr)
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='fetch',
                                 description='ETF 数据抓取（全部实时，失败不沿用旧值）')
    ap.add_argument('--market', action='store_true', help='市场快照 market.json')
    ap.add_argument('--national', action='store_true', help='宽基 ETF 份额')
    ap.add_argument('--sector', action='store_true', help='指数行业权重')
    ap.add_argument('--news', action='store_true', help='财经快讯')
    ap.add_argument('--all', action='store_true', help='全部任务')
    ap.add_argument('--weeks', type=int, default=30, help='份额回补周数（默认 30）')
    ap.add_argument('--dry-run', action='store_true', help='行业权重只打印不落盘')
    args = ap.parse_args(argv)

    names = [n for n in ('market', 'national', 'sector', 'news') if getattr(args, n)]
    if args.all or not names:
        names = ['market', 'national', 'sector', 'news']

    # 每个任务只拿自己的参数：national 认 --weeks，sector 认 --dry-run，market 无参数
    sub_argvs = {}
    if 'national' in names:
        sub_argvs['national'] = ['--weeks', str(args.weeks)]
    if 'sector' in names and args.dry_run:
        sub_argvs['sector'] = ['--dry-run']

    results = run(names, sub_argvs)
    failed = [n for n, r in results.items() if not r['ok']]
    for name, r in results.items():
        print('%-9s %s  %.1fs%s' % (name, 'OK  ' if r['ok'] else 'FAIL',
                                    r['seconds'], '' if r['ok'] else '  ' + str(r['error'])))
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
