# -*- coding: utf-8 -*-
"""数据抓取命令行：python scripts/fetch.py [--market] [--national] [--sector] [--all]

每日流程里由 daily.sh 调用；失败只会保留上次快照，不会让页面更新失败。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from etfquant.datasource.fetch import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
