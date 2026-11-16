# -*- coding: utf-8 -*-
"""指标层统一入口：一次性算出一只标的的全部技术面特征。

唯一实现位于 features.py（生产持仓 / 观察池 / 回测共用），本模块只负责：
  · 把逐日特征复制成一只标的的扁平字典；
  · 并入实时价（last / change_pct）与折溢价；
  · 给出可观测的状态文本（不再使用「真突破 = 出货」这类超出证据的命名）。
"""
from . import premium
from .. import config, features


STATE_TXT = {
    'bull': '多头排列', 'bear': '空头排列', 'tangle': '聚集缠绕', 'mixed': '交织',
}


def five_state(d):
    if not d.get('stand_back'):
        return '未站回MA5'
    if d.get('days_above_ma5', 0) >= 3:
        return '站上MA5第%d日' % d['days_above_ma5']
    return '站回MA5 · %d日' % d.get('days_above_ma5', 0)


def vol_desc(d):
    vr, chg = d.get('vol_ratio'), d.get('change_pct', 0.0)
    if vr is None:
        return '量比不可用'
    if d.get('expand'):
        return '放量下跌' if chg < 0 else '放量上涨'
    if d.get('shrink'):
        return '缩量回调' if chg < 0 else '缩量上行'
    return '量能平淡'


def cycle_phase(d):
    """可观测阶段（不使用 A杀/B反/C杀 叙事标签）。"""
    c, ma10, ma20 = d.get('last'), d.get('ma10'), d.get('ma20')
    if c is None or ma10 is None or ma20 is None:
        return '未知（数据不足）'
    if d.get('below_ma10_2d', 0) >= 2 and c < ma20:
        return '下行趋势（连续低于MA10且低于MA20）'
    if d.get('ma_tangle'):
        return '均线缠绕 · 方向未定'
    if d.get('ma_bull') and d.get('stand_back'):
        return '上行趋势（多头排列且站上MA5）'
    if c < ma10 and not d.get('ma_bull'):
        return '弱势（低于MA10，均线未多头）'
    return '震荡区间'


def breakout_label(d):
    n = d.get('true_breakout_count', 0)
    if d.get('false_breakout'):
        return '放量下跌破MA20（可观测）'
    if n == 4:
        return '突破四条全中'
    return '突破四条 %d/4' % n


def analyze(bars, spot_row, cfg=None):
    cfg = cfg or config.cfg()
    fr = features.frame(bars, cfg)
    d = features.last_dict(fr)
    if not d:
        return None

    code = str(_val(spot_row, 'code'))
    name = str(_val(spot_row, 'name'))
    last = _val(spot_row, 'last')
    try:
        last = float(last)
    except (TypeError, ValueError):
        last = d['close']
    chg = _val(spot_row, 'change_pct')
    try:
        chg = float(chg)
    except (TypeError, ValueError):
        chg = d['change_pct']

    f = dict(code=code, name=name, last=last, change_pct=chg)
    f.update(d)
    f.update(premium.compute(spot_row, cfg['strategy']))

    f['five_state'] = five_state(d)
    f['ma_state'] = (STATE_TXT['bull'] if d['ma_bull'] else
                     STATE_TXT['bear'] if d['ma_bear'] else
                     STATE_TXT['tangle'] if d['ma_tangle'] else STATE_TXT['mixed'])
    f['vol_desc'] = vol_desc(d)
    f['vol_state'] = ('放量' if d['expand'] else '缩量' if d['shrink'] else '平量')
    f['cycle_phase'] = cycle_phase(d)
    f['breakout_label'] = breakout_label(d)
    f['true_breakout_items'] = {
        '不破关键位': bool(d.get('tb_hold_key')),
        '明显缩量': bool(d.get('tb_shrink')),
        '慢跌快涨': bool(d.get('tb_slow_fast')),
        '有承接': bool(d.get('tb_support')),
    }
    # 兼容旧字段：前端与报告仍有引用
    f['premium'] = f['premium_state']
    f['signal_date'] = d['signal_date']
    return f


def _tb(d, key):
    return bool(d.get(key, False))


def _val(row, key, default=None):
    """兼容 dict / DataFrame.itertuples / 以 code 为索引的 Series。"""
    if hasattr(row, 'get') and key in row:
        return row.get(key)
    if key == 'code' and getattr(row, 'name', None) is not None:
        return row.name
    try:
        return row[key]
    except Exception:
        return default
