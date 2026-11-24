# 工具脚本（不参与每日运行）

这些是一次性/研究性工具，`scripts/daily.sh` 不会调用它们。日常只需要
`bash scripts/daily.sh`（取数 → 研究 → 页面 → 推送）。

| 文件 | 用途 |
|---|---|
| `gen_snapshot.py` | 重新生成离线演示快照（`data/snapshot/`），用于不联网跑通全链路 |
| `run_backtest.py` | 历史回测入口 |
| `compare_rules.py` / `compare_v3.py` / `compare_chan.py` | 规则版本、仓位方案、缠论三种口径的对照实验，产出放 `docs/archive/` |
| `gen_page_demo.py` | 用演示数据生成一份页面样本（不覆盖线上 `web/index.html`） |
| `audit.py` | 对已生成的持仓数据包做五项指标评估 |
| `_env.py` | 让工具脚本能 import `src/etfquant` 的三行 shim |

约定：工具脚本可以读写 `data/` 与 `docs/`，但不得修改 `web/index.html` 与
`web/analysis_packet.json`——那两个文件只由 `scripts/run_update.py` 产出。
