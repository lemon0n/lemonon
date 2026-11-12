# -*- coding: utf-8 -*-
"""回测占位：复用 60 日净值口径输出绩效，真实实现接 AKQuant runner / walkforward。"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))
from etfquant import config
from etfquant.portfolio import positions
from etfquant.portfolio import health as H


def main():
    cfg = config.cfg()
    port = positions.load(cfg)
    # 按市值加权构造 60 日组合净值 → 夏普 / 卡玛 / 最大回撤
    perf = H._perf(port['rows'], cfg)
    print(json.dumps({'mode': 'local-60d', 'perf': {k: v for k, v in perf.items() if k != 'nav'},
                      'nav_points': len(perf['nav']),
                      'note': '占位实现，正式回测需接入 AKQuant runner / walkforward'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
