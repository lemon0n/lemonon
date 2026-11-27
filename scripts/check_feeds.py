# -*- coding: utf-8 -*-
"""scripts/check_feeds.py：数据链主/副通道体检入口。"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from etfquant.datasource import feeds  # noqa: E402

if __name__ == '__main__':
    sys.exit(feeds.main())
