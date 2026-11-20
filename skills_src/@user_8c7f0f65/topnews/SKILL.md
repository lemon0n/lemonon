---
name: topnews
version: "8.8.9"
description: 全时段 A 股舆情分析技能。用户想看今天的行情、盘前/盘中/盘后简报、财联社电报快讯、美股隔夜表现、期货大宗商品、主力资金和两融数据，或要求给出当日市场定性（偏多/偏空/震荡）与操作建议时使用。自动采集东方财富、新浪财经、财联社三路公开数据，量化情感评分并生成结构化简报，无需 API Key。
license: MIT
agent_created: true
metadata:
  author: qclaw
  display_name: "股票舆情智能AI助手"
  display_name_en: "Stock Sentiment AI Assistant"
  description_zh: "一句话生成全时段 A 股舆情简报：财联社电报、美股隔夜、期货大宗、主力资金、两融数据全量采集，自动情感评分 + 板块关联 + 偏多偏空定性，免配置 API Key。"
  description_en: "One-line full-day A-share sentiment briefing: Cailianpress telegraph, US stocks, futures, main fund flow and margin data, with quantified sentiment scoring, sector mapping and market verdicts. No API key required."
  visibility: "public"
---

# 股票舆情智能AI助手

按交易时段采集全球市场数据与财经资讯，生成结构化舆情简报，并给出当日市场定性（偏多 / 偏空 / 震荡）与分风格操作建议。

## 功能概述

- **美股行情**：道琼斯、纳斯达克、标普500 实时收盘数据（东财主源 + 新浪备源）
- **期货市场**：富时A50期指、原油、黄金、铜、白银、铁矿石、螺纹钢、沪铜、沪铝（新浪主源 + 东财主连合约备源）
- **财联社电报**：7×24 小时快讯，自动情感分类（利好/利空/中性）+ 板块关联
- **宏观与国际**：国内政策要闻 + 国际财经新闻（东财专栏 + 新浪滚动，关键词自动分类）
- **资金面**：沪深两市主力资金净流入 + 全市场两融数据（融资余额 / 融资净买入）
- **智能结论**：多维度加权评分，自动判定当日市场环境（偏多/偏空/震荡），附保守/稳健/激进三档操作建议

## 分析时段

按当前时间自动选择，也可显式指定：

| Action | 时段 | 时间窗口 | 分析重点 |
|--------|------|----------|----------|
| `pre_market` / `run_now` | 盘前 | 05:00-09:25 | 开盘预测、隔夜消息消化 |
| `intraday` | 盘中 | 09:30-15:00 | 实时舆情、盘中动态 |
| `midday` | 午盘 | 11:30-13:00 | 上午复盘、下午前瞻 |
| `after_market` | 盘后 | 15:00-次日盘前 | 次日预判、龙虎榜 |
| `weekend` | 周末 | 周六周日 | 下周策略制定 |
| `holiday` | 假日 | 法定节假日 | 节后策略规划 |
| `collect` | — | 任意 | 仅采集原始数据（JSON），不生成报告 |
| `help` | — | 任意 | 返回可用 actions 与技能信息 |

## 技能入口

```python
from news_skill_handler import skill_handler

# 立即执行一次（默认盘前）
result = skill_handler({'action': 'run_now'})
print(result['report'])

# 盘中分析（当前时段）
result = skill_handler({'action': 'intraday'})
print(result['report'])

# 仅采集数据（不生成报告）
result = skill_handler({'action': 'collect'})
print(result['data'])
```

命令行方式：

```bash
python news_skill_handler.py --now            # 立即执行（盘前）
python news_skill_handler.py --period intraday # 指定时段
python main.py --now                           # 立即执行一次
python main.py --period after_market           # 指定时段执行
python main.py --schedule                      # 每天 REPORT_TIME 定时执行
```

## 返回值格式

```json
{
    "success": true,
    "action": "run_now",
    "period": "pre_market",
    "timestamp": "2026-10-28 14:20:00",
    "report": "完整简报文本...",
    "data_summary": {
        "美股行情": 3,
        "期货市场": 9,
        "财联社新闻": 30,
        "宏观与国际": 30,
        "资金面": 3
    },
    "verdict": "🎯 市场定性：偏多 | 🟢 情感分 +0.51（乐观） | 💥 影响等级 高",
    "total_items": 75
}
```

简报存档：`reports/YYYY-MM-DD_<period>_brief.txt`

## 文件结构

```
topnews/
├── SKILL.md              # 技能文档（本文件）
├── skill.json            # 技能元数据
├── news_skill_handler.py # 技能统一入口（含全 action CLI）
├── main.py               # 独立运行入口（--now / --period / --schedule）
├── config.py             # 配置管理（请求头 / 超时 / 推送时间）
├── scheduler.py          # 定时调度（APScheduler cron）
├── collectors/           # 数据采集模块
│   ├── base.py           #   基础采集器（httpx 异步客户端）
│   ├── us_stock.py       #   美股行情（东财主源 + 新浪备源）
│   ├── futures.py        #   期货市场（新浪主源 + 东财主连备源）
│   ├── cls_news.py       #   财联社电报（v1 签名接口）
│   ├── macro_news.py     #   宏观政策/国际要闻（东财 + 新浪）
│   └── capital_flow.py   # 资金面（主力资金 + 两融）
├── analysis/             # 分析模块
│   ├── sentiment.py      #   情感量化（连续量表 -1.0 ~ +1.0）
│   ├── importance.py     #   重要性评估（1-10 分）
│   └── sector.py         #   板块关联映射
├── report/
│   └── generator.py      # 简报生成器（时段感知标题/板块/操作建议）
├── notifiers/
│   └── __init__.py       # 推送模块（控制台 / 文件存档）
├── reports/              # 简报存档目录（运行时生成）
├── .env.example          # 环境变量模板
└── requirements.txt      # Python 依赖
```

## 数据源

| 数据源 | 接口 | 类型 | 说明 |
|--------|------|------|------|
| 财联社 v1 | www.cls.cn/v1/roll/get_roll_list | 电报快讯 | 需 sign 校验：`md5(sha1(按 key 字典序拼接的 query 串))`，零密钥本地计算 |
| 东方财富 | push2.eastmoney.com | 美股指数 / 期货主连 / 两市主力资金 | |
| 东方财富 | datacenter-web.eastmoney.com | 全市场两融（RPTA_RZRQ_LSHJ） | 日频 |
| 新浪财经 | hq.sinajs.cn | 行情备源（美股/期货） | |
| 新浪 Feed | feed.mix.sina.com.cn | 滚动财经新闻 | |

> 北向资金自 2024-08 起不再盘中实时披露净流入，已从资金面移除，改用「两市主力资金净流入 + 两融」两路仍公开的权威口径。

## 配置说明

无需任何 API Key。可选配置：复制 `.env.example` 为 `.env` 并调整：

```
REPORT_TIME=06:30     # 定时推送时间（仅 --schedule 模式生效）
```

## 依赖

```
httpx>=0.27.0
python-dotenv>=1.0.1
apscheduler>=3.10.4
```

## 变更记录

- 8.8.9
  - 财联社接口迁移：旧 `nodeapi/telegraphList` 已下线（404），改用 v1 签名接口，修复电报快讯全空的问题
  - 资金面重构：移除 akshare 依赖与北向净流入（披露规则已变），改接两市主力资金 + 全市场两融
  - 期货源重构：新浪为主源（A50/原油/外盘齐全），东财主连合约为备源，消除解析报错
  - 时段修复：`main.py --period` 透传到报告生成器，盘中/盘后标题不再误显示为"盘前"
  - 依赖瘦身：移除未使用的 beautifulsoup4 / lxml / akshare，仅保留 httpx + dotenv + apscheduler
- 2.0.0：全时段分析框架（盘前/盘中/午盘/盘后/周末/假日）
- 1.0.0：早盘简报采集与推送
