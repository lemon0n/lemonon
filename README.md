# 中国 ETF 量化观察台

在线页面：[lemon0n.github.io/lemonon](https://lemon0n.github.io/lemonon/)

公开 ETF 观察与组合研究工具。生成的 `web/index.html` 为自包含页面，可直接打开。规则动作由确定性模型计算；离线合成数据仅用于演示。每日操作见[运行说明](docs/每日运行说明.md)，个人 LLM 工作流见[持仓分析指导](docs/持仓分析每日运行指导.md)。

## 快速开始

```bash
python3.11 -m pip install -r requirements.txt
python3.11 scripts/run_update.py
python3.11 -m pytest tests/ -q
```

离线预览使用 `python3.11 scripts/run_update.py --snapshot`，输出状态为 `DEMO`，不作交易依据。

持仓分析在本机解密并生成报告和私有数据包。口令只通过环境变量传入，输出路径建议放在仓库外：

```bash
POSITIONS_PASSPHRASE="$POSITIONS_PASSPHRASE" python3.11 scripts/analyze_positions.py \
  --out /tmp/持仓分析报告.md --packet /tmp/positions_packet.json
```

模型不承诺收益或成交；无有效证据时应保持观察。不要将明文持仓或私有分析数据包放入公开网页或提交到仓库。

## 架构（单一事实源）

```
真实行情（东财 → 腾讯 → 新浪）        持仓密文（本机/服务端解密）
        │                                    │
        └────────► 数据质量层 quality.py ◄────┘
                        │  OK / DEGRADED / ABSTAIN / DEMO
                        ▼
              features.py（唯一指标实现：量比、上影线取倒数第三根、突破四条…）
                        │
                        ▼
        methodology.decide()（唯一决策函数，规则卡 config/methodology.yaml v2.0）
                        │  ADD / TRIM / CLEAR / HOLD / ABSTAIN
                        ▼
        portfolio/execution.py（目标权重 → 目标份额 → 费用 → 执行后复核）
                        │
                        ▼
              analysis_packet.json（不可变 run_id + input_hash）
                 │            │             │
              网页渲染      Markdown 报告   回测/审计
```

硬约束：

1. 规则决策由 `methodology.decide()` 生成；页面不自行推导另一套动作；
2. 关键数据失败时输出 `ABSTAIN`，不以合成快照继续给交易动作；
3. 回测与生产共用特征、规则和费用定义；
4. 应用内不调用 LLM；个人 LLM 分析规范见[持仓分析指导](docs/持仓分析每日运行指导.md)。

## 页面「刷新行情」

顶部右侧按钮用免费 JSONP 接口拉最新价，只更新价格与价位；**等级与动作不会因盘中价改变**——
日频收盘信号必须重跑脚本才会更新，避免把旧均线和新价拼成「新信号」。

## 数据口径与降级

| 通道 | 主 | 兜底 1 | 兜底 2 | 最终 |
|---|---|---|---|---|
| ETF 日线 | 东财 `fund_etf_hist_em` | 腾讯 `fqkline` | 新浪 `getKLineData` | 离线快照（标记合成） |
| 实时价 | 东财 `fund_etf_spot_em`（含 IOPV） | 腾讯 `qt.gtimg.cn` | 新浪 `hq.sinajs.cn` | 离线快照 |
| 基准指数日线 | 腾讯 `fqkline` | 新浪 `getKLineData` | — | 离线快照 |
| 板块（31 申万一级） | 东财 `ulist.np/get` | 腾讯板块排行 | — | 离线快照 |
| 宏观 / 资讯 / 日历 / 估值 | 离线快照（每项带可点击来源链接） | — | — | — |

- 决策输入（日线 / 实时价 / 基准指数）任一为快照 → `status=DEMO`，不输出交易动作；
- 行情陈旧（超过 5 个自然日）、OHLC 矛盾、重复日期 → `ABSTAIN`，并给出 `field + expected + actual`；
- 兜底行情源无 IOPV → 折溢价显示「数据不可用」，**缺失不当作满足**，该规则不命中；
- 东财 push2 触发限流立即放弃、不重试（重试会把 5 分钟封禁拉长到 40 分钟）。

## 目录

```
config/         methodology（规则卡 v2.0）/ risk（组合约束与执行政策）/ strategy / universe / schedule
data/snapshot/  离线快照（ETF 日线、指数日线、spot、板块、market.json）
data/runs/      每次运行的不可变数据包归档
data/packets/   本地持仓分析数据包（不要提交）
docs/           方法论蒸馏 / 回测报告 / 每日运行说明 / 持仓分析指导
src/etfquant/   features / quality / methodology / pricing / packet / datasource / indicators /
                signals / portfolio（positions, execution, risk, analysis）/ backtest / webgen
scripts/        run_update（唯一入口）/ analyze_positions / run_backtest / gen_snapshot / positions_crypto
web/            index.html + analysis_packet.json（唯一交付物）+ positions.enc.json（密文）
tests/          pytest（数据契约 / 决策契约 Python↔JS / 回测最小反例 / 无密钥护栏）
```

## 隐私与边界

- 持仓以 **AES-256-GCM** 密文保存在 `web/positions.enc.json`，口令经 PBKDF2-SHA256 派生，
  解密只在本机浏览器（或设置了环境变量的服务端进程）完成；仓库里没有明文持仓。
- 不接券商交易接口、不做盘中轮询 / websocket、不实时监控、不代客理财、不承诺盈利。
- 页面「刷新行情」只更新价格；持仓设置里的令牌只存本机浏览器，请使用仅本仓库 `Contents: Read and write` 的 fine-grained PAT。
