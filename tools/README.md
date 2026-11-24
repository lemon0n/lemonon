# 工具脚本（不参与每日运行）

这些是一次性/研究性工具，`scripts/daily.sh` 不会调用它们。日常只需要
`bash scripts/daily.sh`（取数 → 研究 → 页面 → 推送）。

| 文件 | 用途 |
|---|---|
| `run_backtest.py` | 历史回测入口（研究用，不影响每日流程） |

约定：工具脚本可以读写 `data/` 与 `docs/`，但不得修改 `web/index.html` 与
`web/analysis_packet.json`——那两个文件只由 `scripts/run_update.py` 产出。
