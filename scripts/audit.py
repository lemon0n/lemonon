# -*- coding: utf-8 -*-
"""持续评估 CLI：读取决策数据包并输出五项指标。

用法：
  python3 scripts/audit.py [--packet data/packets/positions_packet.json]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from etfquant import audit, config, packet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--packet', default=os.path.join(
        config.ROOT, 'data', 'packets', 'positions_packet.json'))
    a = ap.parse_args()
    if not os.path.exists(a.packet):
        print('未找到数据包：%s（先运行 scripts/analyze_positions.py）' % a.packet)
        return 2
    with open(a.packet, encoding='utf-8') as f:
        pkt = json.load(f)
    decision = pkt.get('decision')
    if not decision:
        print('数据包不含统一决策契约（decision），无法评估')
        return 2
    res = audit.evaluate(decision)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
