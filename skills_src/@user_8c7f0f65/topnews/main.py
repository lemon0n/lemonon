from __future__ import annotations

import asyncio
import argparse
import logging
import sys
from datetime import datetime

from collectors import (
    USStockCollector,
    FuturesCollector,
    CLSNewsCollector,
    MacroNewsCollector,
    CapitalFlowCollector,
)
from notifiers import ConsoleNotifier, FileNotifier
from report import ReportGenerator
from scheduler import Scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("morning_brief")

PERIODS = ["pre_market", "intraday", "midday", "after_market", "weekend", "holiday"]


async def collect_all() -> dict:
    collectors = [
        USStockCollector(),
        FuturesCollector(),
        CLSNewsCollector(),
        MacroNewsCollector(),
        CapitalFlowCollector(),
    ]

    all_data = {}
    tasks = [c.collect() for c in collectors]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for c, result in zip(collectors, results):
        if isinstance(result, Exception):
            logger.error("[%s] 采集异常: %s", c.category, result)
            all_data[c.category] = []
        else:
            all_data[c.category] = result.items
            logger.info("[%s] 采集完成, %d 条数据", c.category, len(result.items))

    for c in collectors:
        await c.close()

    return all_data


async def generate_and_notify(period: str = "pre_market"):
    all_data = await collect_all()

    generator = ReportGenerator()
    report = generator.generate(all_data, period=period)

    notifiers = [
        ConsoleNotifier(),
        FileNotifier(label=period),
    ]

    for notifier in notifiers:
        try:
            await notifier.send(report)
        except Exception as e:
            logger.error("推送失败 [%s]: %s", type(notifier).__name__, e)

    logger.info("简报生成完成（%s）", period)
    return report


async def run_once(period: str = "pre_market"):
    report = await generate_and_notify(period)
    return report


async def run_scheduled():
    sched = Scheduler(job_func=lambda: generate_and_notify("pre_market"))
    sched.start()
    logger.info("调度模式启动，按 Ctrl+C 退出")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        sched.stop()


def main():
    parser = argparse.ArgumentParser(description="全时段股票舆情分析技能")
    parser.add_argument("--now", action="store_true", help="立即执行一次（默认盘前分析）")
    parser.add_argument("--period", type=str, default=None, choices=PERIODS,
                        help="指定分析时段（默认 pre_market）")
    parser.add_argument("--schedule", action="store_true", help="启动定时调度模式")
    args = parser.parse_args()

    if args.schedule:
        asyncio.run(run_scheduled())
    else:
        period = args.period or "pre_market"
        asyncio.run(run_once(period))


if __name__ == "__main__":
    main()
