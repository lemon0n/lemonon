# -*- coding: utf-8 -*-
"""分诊：不再维护第二套 A/B/C/D 逻辑。

历史问题（指导书 P0-03）：triage.py 与 methodology.py 各写一套动作求值，
同一形态在持仓报告与观察池里可能得到不同等级。现在本模块只做两件事：

  1. 调用唯一决策函数 methodology.decide()；
  2. 把结果包装成前端 / 报告需要的展示字段（风险标签、周期位置、突破状态）。

任何「先算等级再猜动作」的分支都已删除。
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
