# 中国 ETF 量化观察台

在线地址：**https://lemon0n.github.io/lemonon/**

一个轻量的公开 ETF 观察工具：跑一次，产出一个**自包含页面** `web/index.html`（CSS / JS / 数据全部内嵌），双击即可打开，不需要本地服务。

> **当前版本 v3（正确性优先）**：数据质量熔断 + 唯一决策契约 + 执行后组合复核 + 与生产同源的回测。
> 每日运行请看 [docs/每日运行说明.md](docs/每日运行说明.md)。
>
> **旧结论已冻结**：此前 `docs/回测报告.md` 中的「样本外年化 6.04% / 胜率 74.7% / 独立验证集」等表述
> 已撤回（样本重叠、口径错误、样本外被用于选参），不得再引用。

## 这个系统能回答什么、不能回答什么

| 能 | 不能 |
|---|---|
| 当前位置与趋势：收盘 / MA5·10·20·60·120、站上 MA5 天数、连续低于 MA10 天数 | 预测明天涨跌 |
| 量能特征：量比、放量 / 缩量（只描述成交，不代表资金净流入） | 判断「主力」在做什么 |
| 相对基准：与同日基准指数比较的 5/20 日超额（基准缺失则为未知） | 跨资产统一相对沪深 300 解释 alpha |
| 规则求值：命中哪条规则、目标权重与目标份额、预计费用、执行后仓位与约束校验 | 保证成交价、保证收益、保证回撤上限 |
| 数据可信度：覆盖、陈旧、合成标记、`OK/DEGRADED/ABSTAIN/DEMO/ERROR` | 冒充个性化最优配置 |

## 运行

```bash
python3.11 -m pip install -r requirements.txt

python3.11 scripts/run_update.py            # 实时取数 → 重写 web/index.html + analysis_packet.json
python3.11 scripts/run_update.py --snapshot # 不联网，用离线快照（结果状态为 DEMO，仅演示）
python3.11 scripts/run_update.py --push     # 生成后自动 commit + push
python3.11 scripts/run_update.py --strict   # 状态非 OK 即退出码 1（适合 CI 报警）
python3.11 scripts/run_update.py --verify   # 只做发布前校验
python3.11 -m pytest tests/ -q              # 60 项测试，不触网（含 Python↔JS 决策契约对拍）

# 持仓专业分析（S1–S5 + 执行后模拟 → Markdown + 数据包）
POSITIONS_PASSPHRASE='口令' python3.11 scripts/analyze_positions.py \
  --out docs/当前持仓分析报告.md --packet data/packets/positions_packet.json

# 回测（固定池 + 时间隔离；最终测试只允许看一次）
python3.11 scripts/run_backtest.py --stage train
python3.11 scripts/run_backtest.py --stage validate
python3.11 scripts/run_backtest.py --stage test
```

退出码：`0` 正常 · `1` strict 下状态非 OK · `2` 运行异常 · `3` 推送/校验失败 · `4` 发布前校验失败。

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

1. 只有一个权威决策结果，网页不得自行推导第二套动作（`web_assets/rules.js` 与 Python 逐字段对拍）；
2. 先有结构化结果，再有报告；
3. 关键数据失败 → `ABSTAIN`，不退回合成快照继续给单；
4. 回测与实盘共用 `features.frame` + `methodology.decide` + 费用定义；
5. LLM 不参与数值与交易决策；
6. 每次运行写 `data/runs/<run_id>.json`，可重放。

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
data/packets/   持仓分析数据包（含目标份额与执行后校验）
docs/           方法论蒸馏 / 回测报告（已冻结旧结论）/ 每日运行说明 / 持仓分析报告（归档）
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
