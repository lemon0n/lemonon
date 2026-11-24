# -*- coding: utf-8 -*-
"""生成「持仓分析页」demo：复用仓库现有的单文件页面，只把持仓改成明文注入。

不是另写一套页面：数据走 webgen.build_data → render，样式/脚本用 web_assets。
demo 与线上的差别只有两点：
  1. 持仓直接以明文注入（跳过口令锁与解密）；
  2. 顶部多一条 DEMO 横幅。
输出仍是一个自包含 HTML，双击即可看。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from etfquant import config, webgen                       # noqa: E402
from etfquant.datasource import loader                    # noqa: E402
from etfquant.llm import storage                          # noqa: E402


def latest_run() -> str:
    base = os.path.join(ROOT, 'data', 'runs')
    names = []
    for day in sorted(os.listdir(base), reverse=True) if os.path.isdir(base) else []:
        d = os.path.join(base, day)
        for run in sorted(os.listdir(d), reverse=True) if os.path.isdir(d) else []:
            p = os.path.join(d, run)
            if os.path.exists(os.path.join(p, 'page_data.json')):
                names.append(p)
        if names:
            break
    if not names:
        raise SystemExit('没有可用的运行目录（先跑 run_research --prepare）')
    return names[0]


def bars_of(code: str, n: int = 180) -> dict | None:
    """持仓日线（页面画均线与结构图用）；取不到就不塞，页面会走自己的取数/回退卡。"""
    try:
        df = loader.daily(code)
    except Exception:
        return None
    if df is None or len(df) < 30:
        return None
    df = df.tail(n)
    def nums(col):
        return [None if v != v else float(v) for v in df[col].tolist()]
    return dict(dates=[str(x)[:10] for x in df['date'].tolist()],
                opens=nums('open'), closes=nums('close'),
                highs=nums('high'), lows=nums('low'), vols=nums('volume'))


def demo_positions(context: dict) -> dict:
    port = context.get('portfolio') or {}
    rows = []
    for p in port.get('positions') or []:
        if not p.get('shares'):
            continue
        rows.append(dict(code=str(p['symbol']), name=p.get('name') or str(p['symbol']),
                         category=p.get('category') or '未分类',
                         shares=int(p['shares']), cost=float(p.get('cost') or 0),
                         settle='T+1', last=p.get('last')))
    bars = {}
    for row in rows:
        b = bars_of(row['code'])
        if b:
            bars[row['code']] = b
    return dict(rows=rows, cash=float(port.get('cash') or 0), bars=bars)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='持仓分析页 demo（明文、不加密）')
    ap.add_argument('--run-dir', help='运行目录；缺省取最近一次')
    ap.add_argument('--out', help='输出路径')
    args = ap.parse_args(argv)

    run_dir = args.run_dir or latest_run()
    data = storage.load_run(run_dir, 'page_data.json')
    context = storage.load_run(run_dir, 'context.json')
    if not data or not context:
        raise SystemExit('缺少 page_data.json / context.json：%s' % run_dir)

    latest = storage.read_latest() or {}
    payload = (latest.get('payload') or {}) if latest.get('run_dir') == run_dir else None
    if payload:
        data['research'] = payload
    brief = storage.load_run(os.path.join(config.ROOT, 'data'), 'brief.json')
    if brief:
        data['brief'] = brief

    demo = demo_positions(context)
    out = args.out or os.path.join(ROOT, 'demo', '持仓分析页_demo.html')
    res = webgen.render(data, config.cfg(), demo=demo, out_path=out)
    print('已生成 %s（%.1f KB｜持仓 %d 只｜现金 ¥%s｜来源 %s）'
          % (res['path'], res['bytes'] / 1024, len(demo['rows']),
             format(round(demo['cash']), ','), os.path.basename(run_dir)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
