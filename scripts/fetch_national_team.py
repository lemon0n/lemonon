# -*- coding: utf-8 -*-
"""抓取宽基 ETF 份额（国家队主要持仓方向），按日累积成序列。

数据源：腾讯行情快照（qt.gtimg.cn，字段 72 = 总份额，单位「份」），
与上交所披露的 ETF 份额一致（510300：4968408.77 万份 = 49684087700 份）。
上交所历史接口不稳定，因此这里按日累积：每次运行追加当天一个点，
序列长了以后页面即可显示「较上次」「近四周」与方向。

抓取失败时保留上次快照，不阻断主流程。
用法：
  python3 scripts/fetch_national_team.py --latest
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'national_team.json')

# 宽基分组：汇金等国家队主要买这几类；159915 在深市，用同一接口即可
GROUPS = {
    '510300': '沪深300',
    '510050': '上证50',
    '510500': '中证500',
    '512100': '中证1000',
    '588000': '科创50',
    '159915': '创业板',
}

SHARE_FIELD = 72


def _symbol(code):
    return ('sh' if code[0] in '569' else 'sz') + code


def fetch():
    """用 curl 取行情快照（requests 在本环境会因代理证书失败）。"""
    syms = ','.join(_symbol(c) for c in GROUPS)
    p = subprocess.run(
        ['curl', '-s', '--max-time', '20', 'https://qt.gtimg.cn/q=' + syms],
        capture_output=True)
    if p.returncode != 0 or not p.stdout:
        return None
    try:
        text = p.stdout.decode('gbk', 'ignore')
    except Exception:
        return None
    out, stamp = {}, None
    for line in text.split(';'):
        line = line.strip()
        if not line or '=' not in line:
            continue
        body = line.split('=', 1)[1].strip().strip('"')
        f = body.split('~')
        if len(f) <= SHARE_FIELD:
            continue
        code = f[2]
        if code not in GROUPS:
            continue
        try:
            shares = float(f[SHARE_FIELD])
        except (TypeError, ValueError):
            continue
        if shares <= 0:
            continue
        out[code] = dict(shares=shares, name=f[1])
        if len(f) > 30 and len(f[30]) >= 8:
            stamp = f[30][:8]
    if not out:
        return None
    date = '%s-%s-%s' % (stamp[:4], stamp[4:6], stamp[6:8]) if stamp \
        else datetime.date.today().isoformat()
    return date, out


def load_old():
    try:
        with open(OUT, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d.get('series'), list) else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--latest', action='store_true', help='只取最新快照')
    ap.parse_args()

    got = fetch()
    if not got:
        print('[警告] ETF 份额快照不可用，保留上次数据', file=sys.stderr)
        return 0
    date, groups = got

    old = load_old() or dict(groups={}, series=[])
    series = [x for x in old.get('series', []) if x.get('date') != date]
    series.append(dict(date=date, groups=groups))
    series.sort(key=lambda x: x['date'])
    series = series[-90:]

    out = dict(as_of=date, unit='份', groups={c: n for c, n in GROUPS.items()},
               source='腾讯行情快照（总份额字段），与上交所 ETF 份额口径一致',
               series=series,
               fetched_at=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print('已更新宽基份额快照：%s（%d 只，序列 %d 期）'
          % (date, len(groups), len(series)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
