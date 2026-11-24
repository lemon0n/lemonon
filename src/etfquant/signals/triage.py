# -*- coding: utf-8 -*-
"""分诊：调用 methodology.decide()，并把结果包装成展示字段。

动作、等级、规则编号一律透传 decide()，不从等级反推动作；
风险标签、周期位置、突破状态由本模块补充。
"""
from .. import methodology as M


def compute(f, rs, cfg, overrides=None, data_status='OK'):
    """f: indicators.analyze 输出；rs: relative_strength.compute 输出。"""
    ov = dict(overrides or {})
    dec = M.decide(f, data_status=data_status, overrides=ov)
    risk_flags = []
    if f.get('false_breakout'):
        risk_flags.append('放量下跌破MA20')
    if f.get('below_ma10_2d', 0) >= 1:
        risk_flags.append('收盘低于MA10 %d 日' % f['below_ma10_2d'])
    if f.get('is_20d_low'):
        risk_flags.append('20日新低')
    if f.get('premium_available') is False:
        risk_flags.append('IOPV 缺失（折溢价未参与判定）')
    if not risk_flags:
        risk_flags = ['无']

    return dict(status=dec['status'], level=dec['level'], action=dec['action'],
                rule_ids=dec['rule_ids'], hits=dec['hits'],
                blocked_by=dec['blocked_by'], unknowns=dec['unknowns'],
                risk_flags=risk_flags,
                cycle_phase=f.get('cycle_phase'), ma_state=f.get('ma_state'),
                five_state=f.get('five_state'), breakout_label=f.get('breakout_label'),
                rs=rs)
