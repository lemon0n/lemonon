# 每日刷新执行说明书（唯一入口）

接到「刷新一次 / 跑每日任务」时，只做一件事：执行下面这条命令，然后汇报结果。

```bash
bash scripts/daily.sh
```

**不要**为了刷新去读 `docs/` 里的任何文件，也不要拆成「先抓这个、再跑那个」。
所有步骤已经写在脚本里，按顺序自动完成。读完本页就够，不需要分析仓库。

---

## 一条命令会做什么

1. 切到 `main`，`git pull --rebase --autostash origin main`；
2. 检查 Python 依赖，缺了就按 `requirements.txt` 安装；
3. 若设置了 `POSITIONS_PASSPHRASE`，生成 `docs/持仓分析报告.md` 与 `data/packets/positions_packet.json`；
4. `scripts/run_update.py --json --push`：实时取数 → 计算 → 生成页面 → 发布前校验 →
   提交并推送 `web/index.html`、`web/analysis_packet.json`、`data/last_run.json`（以及第 3 步两份持仓文件）；
5. 若 `config/llm.yaml` 的 `enabled=true` 且本地模型可连，`run_update.py` 会顺带跑
   LLM 研究层（Research → Proposal → Red Team → Revision → 风控 → 订单草案），
   把结果内嵌进同一个页面后只推送一次；模型不可用时页面照常发布，状态标 `LLM_FAILED`；
6. 打印状态、数据日、降级明细。

GitHub Actions 只做 Pages 发布，不再定时取数；每日更新一律由这条命令完成。

## 怎么看结果

最后一行是一条 JSON，看三个字段：

| 字段 | 合格值 |
|---|---|
| `status` | `OK`（其它：`DEGRADED` 降级、`DEMO` 演示、`ABSTAIN` 数据不足） |
| `validation.ok` | `true` |
| `degraded` | `false` |
| `research.status` | `APPROVED` / `REJECTED`（业务结论）或 `SKIPPED` / `LLM_FAILED`（未跑/不可用，不算故障） |

汇报时给：退出码、`status`、`data_date`、`degraded`、`skipped`、有无推送成功。

## 退出码

| 码 | 含义 | 处理 |
|---|---|---|
| 0 | 成功（含产物无变化） | 结束 |
| 4 | 发布前校验未通过，**未推送** | 把校验错误原文报出来，不要重试、不要改阈值 |
| 3 | 产物已生成但提交/推送失败 | 多半是远端有新提交，原样再跑一次 |
| 2 | 运行异常 | 读报错定位，不要盲目重跑 |

## 硬性约束

- **不要加 `--snapshot`**：它用离线演示数据，会把线上页面覆盖成 `DEMO`。
- **不要手动提交** `web/index.html`、`web/analysis_packet.json`、`data/last_run.json`、
  `docs/持仓分析报告.md`、`data/packets/positions_packet.json`；它们只由这条命令产出。
- **不要改阈值、规则或 `config/` 参数**让校验通过；校验失败是要报告的问题，不是要绕过的障碍。
- 产物没变化时命令也会返回 0，这是正常情况，不要为了“有提交”去改文件。
- 只想离线调试、不拉远端：`SKIP_PULL=1 bash scripts/daily.sh`，其余不变。

## 持仓口令

持仓报告和数据包随仓库公开发布（含代码、份额、成本、浮动盈亏）。
口令只从环境变量读取，绝不写入文件：

```bash
export POSITIONS_PASSPHRASE='你的口令'
bash scripts/daily.sh
```

未设置时自动跳过持仓分析，只更新市场页，退出码不受影响。
持仓分析单独失败只告警，不阻断市场页。

## 文件地图（只在你需要排查时看）

| 路径 | 作用 |
|---|---|
| `scripts/daily.sh` | 唯一入口，别绕开它 |
| `scripts/run_update.py` | 取数、生成、校验、提交推送（研究层也在这里内嵌，默认自动判断） |
| `scripts/run_research.py` | 只跑 LLM 研究层，不推送 |
| `src/etfquant/` | 计算与页面打包（`webgen.py` 出 HTML） |
| `src/etfquant/llm/` | LLM 研究决策层（四段链、风控、订单、报告、接口） |
| `prompts/`、`config/llm.yaml`、`config/risk_policy.yaml` | 提示词与模型/风控配置 |
| `data/runs/`、`data/ledger/` | 研究运行产物与研究记忆（已 gitignore，含权重） |
| `data/snapshot/`、`data/cache/` | 输入快照与日线缓存 |
| `docs/页面区块对照.md` | 页面上每一块由谁产出，排查时查这一份 |
| `docs/` | 其余是设计文档与历史方案，**不参与每日流程** |

## 不要做的事

- 不要把 `docs/` 里的施工指南、运行链条、方法论当成刷新步骤。
- 不要并行跑多个抓取脚本；`daily.sh` 内部已按依赖顺序执行。
- 不要在看到推送冲突时手工 rebase 产物文件；先重跑一次 `daily.sh`（退出码 3 的自愈路径）。
- 不要手改 `data/runs/*/06_final_plan.json` 或 `data/research_latest.json`：它们是研究层的原始产物，
  改了就无法重放与审计（`python3 -m etfquant.llm.cli replay` 会报哈希不一致）。
- 不要把 `provider: mock` 的脚本结果当成投资建议：该状态是 `LLM_MOCK`，永不生成可执行订单。
- 不要为了让研究层出结论去放宽 `config/risk_policy.yaml`；风控退回是要报告的问题，不是要绕过的障碍。
