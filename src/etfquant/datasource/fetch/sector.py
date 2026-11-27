# -*- coding: utf-8 -*-
"""指数 → 申万一级行业权重：页面「主要板块 / 组合行业暴露」的唯一数据源。

来源（全部为公开披露，不估算）：
  · 沪深300 / 中证500 / 科创50：东方财富数据中心「指数成分」权重
    （reportName=RPT_INDEX_TS_COMPONENT，TYPE=1/3/4，权重和 99.9~100.1）；
  · 创业板指：国证指数官网「样本详情」导出表（公开权重只覆盖约 50%，
    其余成分按流通市值补齐，JSON 中 method 标 official+ff）。
个股所属行业取东方财富 f100（申万二级），再按 config/sw_industry_map.json
归并到申万一级；无法归并的二级行业并入「其他」，并在 unmapped 中列出，不静默丢弃。

失败策略：任一指数的权重校验不通过（和不在 99~101、行业名不在申万一级名录里），
该指数不参与映射；一个都没有时写空 indices，由页面显示「未覆盖」。
**不沿用上次结果**：旧权重不得冒充当前权重。

用法：
  python3 scripts/fetch_index_sector_weights.py            # 抓取并写 data/live/index_sector_weights.json
  python3 scripts/fetch_index_sector_weights.py --dry-run  # 只打印结果，不落盘
"""
import argparse
import csv
import datetime
import json
import os
import subprocess
import sys
import tempfile

import yaml

from ... import config
ROOT = config.ROOT
OUT = os.path.join(ROOT, 'data', 'live', 'index_sector_weights.json')
SW_LEVEL1 = os.path.join(ROOT, 'config', 'sw_industry_map.json')
UNIVERSE = os.path.join(ROOT, 'config', 'universe.yaml')
SW_MAP = os.path.join(ROOT, 'config', 'sw_industry_map.json')

# 东方财富指数成分报表的 TYPE 编号
EM_TYPE = {'000300': 1, '000905': 3, '000688': 4}
CN_INDEX = '399006'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36'


def _curl(url, referer=None):
    """取回字节；requests 在本环境受代理证书影响，统一用 curl。"""
    tmp = tempfile.mktemp()
    cmd = ['curl', '-s', '-L', '--max-time', '30', '-A', UA]
    if referer:
        cmd += ['-H', 'Referer: ' + referer]
    cmd += [url, '-o', tmp]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 or not os.path.exists(tmp):
        return None
    with open(tmp, 'rb') as f:
        data = f.read()
    os.remove(tmp)
    return data or None


def _curl_json(url):
    raw = _curl(url)
    if not raw:
        return None
    try:
        return json.loads(raw.decode('utf-8'))
    except ValueError:
        return None


def load_universe():
    with open(UNIVERSE, encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    return {str(e['code']): str(e['benchmark']) for e in cfg['etfs'] if e.get('benchmark')}


def load_sectors():
    """申万一级名录来自配置，不依赖任何行情快照文件。"""
    with open(SW_LEVEL1, encoding='utf-8') as f:
        doc = json.load(f)
    names = set(doc.get('level1') or [])
    if not names:
        raise RuntimeError('config/sw_industry_map.json 缺少 level1 行业名录')
    return names


def load_sw_map():
    with open(SW_MAP, encoding='utf-8') as f:
        d = json.load(f)
    return d['map']


def em_members(type_id):
    """指数成分与权重；返回 ([(code, weight, 二级行业)], 数据日)，失败返回 (None, None)。"""
    url = ('https://datacenter-web.eastmoney.com/api/data/v1/get'
           '?reportName=RPT_INDEX_TS_COMPONENT&columns=SECURITY_CODE,WEIGHT,INDUSTRY,MAXTRADEDATE'
           '&pageSize=500&pageNumber=%d&filter=(TYPE%%3D%%22%d%%22)&source=WEB&client=WEB')
    rows, page, day = [], 1, ''
    while page <= 4:
        d = _curl_json(url % (page, type_id))
        res = (d or {}).get('result')
        if not res:
            return (rows or None), (day or None)
        rows += res.get('data') or []
        if page >= (res.get('pages') or 1):
            break
        page += 1
    out = []
    for r in rows:
        try:
            w = float(r.get('WEIGHT'))
        except (TypeError, ValueError):
            continue
        if w <= 0:
            continue
        day = max(day, str(r.get('MAXTRADEDATE') or '')[:10])
        out.append((str(r['SECURITY_CODE']), w, (r.get('INDUSTRY') or '').strip()))
    return (out or None), (day or None)


def cn_members(index_code):
    """国证指数样本：导出 xls；返回 ([(code, 权重或 None, 国证门类)], 数据日)。"""
    raw = _curl('https://www.cnindex.com.cn/sample-detail/download?indexcode=' + index_code,
                referer='https://www.cnindex.com.cn/')
    if not raw or len(raw) < 1000:
        return None, None
    tmp = tempfile.mktemp(suffix='.xls')
    with open(tmp, 'wb') as f:
        f.write(raw)
    try:
        import xlrd
        sheet = xlrd.open_workbook(tmp).sheet_by_index(0)
        out, day = [], ''
        for r in range(1, sheet.nrows):
            code = str(sheet.cell_value(r, 1)).strip().split('.')[0]
            if not (len(code) == 6 and code.isdigit()):
                continue
            try:
                w = float(sheet.cell_value(r, 4))
            except (TypeError, ValueError):
                w = None
            day = max(day, str(sheet.cell_value(r, 0)).strip()[:10])
            out.append((code, w, str(sheet.cell_value(r, 3)).strip()))
        return (out or None), (day or None)
    except Exception:
        return None, None
    finally:
        os.remove(tmp)


def stock_industries():
    """全 A 股 code → (申万二级, 流通市值亿元)，用于补齐与缺失行业。"""
    url = ('https://push2.eastmoney.com/api/qt/clist/get?pn=%d&pz=100&po=1&np=1'
           '&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048'
           '&fields=f12,f21,f100')
    out, page = {}, 1
    while page <= 70:
        d = _curl_json(url % page)
        diff = ((d or {}).get('data') or {}).get('diff') or []
        if not diff:
            break
        for r in diff:
            code = str(r.get('f12') or '')
            if len(code) != 6:
                continue
            try:
                cap = float(r.get('f21') or 0) / 1e8
            except (TypeError, ValueError):
                cap = 0.0
            out[code] = ((r.get('f100') or '').strip(), cap)
        page += 1
    return out


def _l1(name, sw):
    """二级 → 一级；带 Ⅱ/Ⅲ 后缀的做一次去后缀重试。"""
    if not name:
        return None
    if name in sw:
        return sw[name]
    for suf in ('Ⅲ', 'Ⅱ'):
        if name.endswith(suf) and name[:-1] in sw:
            return sw[name[:-1]]
    return None


def build_index(members, sw, sectors, float_only=None):
    """成分 → {一级: 权重}，并把补权重的来源记下来。"""
    total_official = sum(w or 0 for _, w, _ in members)
    missing = [(c, ind) for c, w, ind in members if w is None]
    alloc = {}
    if missing and float_only is not None:
        caps = {c: float_only.get(c, ('', 0))[1] for c, _ in missing}
        denom = sum(caps.values())
        residual = max(0.0, 100.0 - total_official)
        if denom > 0:
            alloc = {c: residual * caps[c] / denom for c in caps}
    acc, unmapped = {}, []
    for code, w, ind in members:
        weight = w if w is not None else alloc.get(code, 0.0)
        if weight <= 0:
            continue
        l1 = _l1(ind, sw)
        if l1 is None or l1 not in sectors:
            unmapped.append(ind or '(空)')
            l1 = '其他'
        acc[l1] = acc.get(l1, 0.0) + weight
    acc = {k: round(v, 2) for k, v in acc.items()}
    return acc, sorted(set(unmapped)), round(total_official, 2)


def _tencent_caps(codes):
    """腾讯批量行情取流通市值（字段 44，单位亿元）。"""
    import requests
    out = {}
    ua = {'User-Agent': UA}
    codes = [str(c) for c in codes]
    for i in range(0, len(codes), 60):
        chunk = codes[i:i + 60]
        syms = ','.join(('sh' if c[0] in '569' else 'sz') + c for c in chunk)
        try:
            r = requests.get('https://qt.gtimg.cn/q=' + syms, headers=ua, timeout=10)
            r.encoding = 'gbk'
        except Exception:
            continue
        for seg in r.text.split(';'):
            if '="' not in seg:
                continue
            body = seg.split('="', 1)[1].rstrip('"').split('~')
            if len(body) < 46:
                continue
            code = str(body[2])[-6:]
            try:
                cap = float(body[44])
            except (TypeError, ValueError):
                continue
            if cap > 0:
                out[code] = cap
    return out


def _em_industries(codes):
    """东财 datacenter 批量取申万一级（BOARD_NAME_LEVEL 第一段）。"""
    import requests
    out = {}
    codes = [str(c) for c in codes]
    for i in range(0, len(codes), 40):
        chunk = codes[i:i + 40]
        flt = '(SECURITY_CODE in ("' + '","'.join(chunk) + '"))'
        url = ('https://datacenter-web.eastmoney.com/api/data/v1/get'
               '?reportName=RPT_F10_BASIC_ORGINFO'
               '&columns=SECURITY_CODE,BOARD_NAME_LEVEL'
               '&pageSize=200&pageNumber=1&filter=' + requests.utils.quote(flt) +
               '&source=WEB&client=WEB')
        try:
            d = requests.get(url, headers={'User-Agent': UA}, timeout=12).json()
        except Exception:
            continue
        for row in ((d.get('result') or {}).get('data') or []):
            code = str(row.get('SECURITY_CODE') or '')
            level = str(row.get('BOARD_NAME_LEVEL') or '').split('-')[0].strip()
            if code and level:
                out[code] = level
    return out


def ff_proxy_weights(members, sectors):
    """自由流通市值加权近似：腾讯流通市值 + 东财申万一级。

    官方权重缺失（例如创业板指只披露「--」）时使用；JSON 里标 method=ff_proxy，
    页面按近似口径展示，不冒充官方权重。
    """
    codes = [c for c, _, _ in members if c]
    if not codes:
        return None, [], '没有成分股'
    caps = _tencent_caps(codes)
    inds = _em_industries(codes)
    total = sum(caps.get(c, 0.0) for c in codes)
    if total <= 0 or len(inds) < max(1, len(codes) // 2):
        return None, [], '缺流通市值或行业数据'
    acc, unmapped = {}, []
    for code in codes:
        cap = caps.get(code, 0.0)
        if cap <= 0:
            continue
        level = inds.get(code) or ''
        if level not in sectors:
            unmapped.append(level or '(空)')
            level = '其他'
        acc[level] = acc.get(level, 0.0) + cap
    weights = {k: round(v / total * 100, 2) for k, v in acc.items()}
    return weights, sorted(set(unmapped)), None


def valid(weights, sectors):
    if not weights:
        return False
    if any(k not in sectors and k != '其他' for k in weights):
        return False
    return 99 <= sum(weights.values()) <= 101


def main(argv=None):
    ap = argparse.ArgumentParser(prog='fetch sector')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    etf_index = load_universe()
    sectors = load_sectors()
    sw = load_sw_map()

    prev = {}
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding='utf-8') as f:
                prev = json.load(f)
        except ValueError:
            prev = {}

    stocks = stock_industries()
    indices, source, method, unmapped, errors, wdate = {}, {}, {}, {}, [], {}
    approximate, stale = {}, False

    for idx in sorted(set(etf_index.values())):
        try:
            if idx in EM_TYPE:
                members, day = em_members(EM_TYPE[idx])
                m = 'official'
            else:
                members, day = cn_members(idx)
                m = 'official+ff'
            if not members:
                raise RuntimeError('未取到成分')
            # 成分表缺行业的，用全市场行业表补；国证表只有门类，一律换成申万二级
            fixed = []
            for code, w, ind in members:
                if idx not in EM_TYPE or not ind:
                    ind = stocks.get(code, ('', 0))[0] or ind
                fixed.append((code, w, ind))
            weights, unm, official_sum = build_index(fixed, sw, sectors, float_only=stocks)
            if not valid(weights, sectors):
                raise RuntimeError('校验未通过：权重和 %.2f' % sum(weights.values()))
            indices[idx] = weights
            source[idx] = ('东方财富数据中心 指数成分权重' if idx in EM_TYPE
                           else '国证指数官网 样本详情导出')
            method[idx] = dict(method=m, official_sum=official_sum)
            if day:
                wdate[idx] = day
            if unm:
                unmapped[idx] = unm
        except Exception as e:                    # 官方失败 → 自由流通市值近似副通道
            note = '%s: %s' % (idx, e)
            proxy, proxy_unmapped, proxy_err = ff_proxy_weights(members or [], sectors)
            if proxy and valid(proxy, sectors):
                indices[idx] = proxy
                source[idx] = '自由流通市值加权近似（腾讯行情 + 东财申万行业）'
                method[idx] = dict(method='ff_proxy')
                approximate[idx] = True
                if proxy_unmapped:
                    unmapped[idx] = proxy_unmapped
                if day:
                    wdate[idx] = day
                errors.append(note + ' → 已用 ff_proxy 近似')
            else:
                errors.append(note + '；近似通道也不可用：%s' % (proxy_err or '数据不足'))
                stale = True

    if not indices:
        print('未取到任何指数权重，写空文件（不回退旧文件）：' + '；'.join(errors),
              file=sys.stderr)

    as_of = max([d for d in wdate.values() if d] or [datetime.date.today().isoformat()])
    doc = dict(
        as_of=as_of,
        fetched_at=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        generated_at=datetime.datetime.now().isoformat(timespec='seconds'),
        stale=bool(stale),
        approximate=dict(approximate),
        unit='%',
        source=source,
        method=method,
        weights_date=wdate,
        indices=indices,
        etf_index=etf_index,
        unmapped=unmapped,
        errors=errors,
    )
    if args.dry_run:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    for idx in sorted(indices):
        print('%s  %d 个行业  权重和 %.2f  %s'
              % (idx, len(indices[idx]), sum(indices[idx].values()), source.get(idx, '')))
    if errors:
        print('降级：' + '；'.join(errors), file=sys.stderr)
    return 0

