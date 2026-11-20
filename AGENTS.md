# 每日更新执行说明（唯一口径）

本文件是自动化执行的唯一入口。任何人或本地模型接到「按每日任务执行一次」的指令时，
只执行下面这一条命令，不要自行拆分、改写或增加步骤。

```bash
bash scripts/daily.sh
```

## 它做什么

一条命令完成全流程，无需额外操作：

1. `git pull --rebase --autostash origin main` —— 同步远端最新代码；
2. 检查依赖，缺失时按 `requirements.txt` 安装；
3. 若设置了 `POSITIONS_PASSPHRASE`，生成持仓分析：
   `docs/持仓分析报告.md` 与 `data/packets/positions_packet.json`；
4. `scripts/run_update.py --json --push` —— 实时取数、计算、生成页面、发布前校验、
   提交并推送 `web/index.html`、`web/analysis_packet.json`、`data/last_run.json`，
   以及第 3 步生成的两份持仓文件；
5. 打印状态、数据日、降级明细。

推送后 GitHub Actions 只做 Pages 发布，不再重新取数或自动生成页面：
定时 cron 已关闭，每日更新一律由本地手动执行本文件第 1 节的命令完成。
Actions 里的「Run workflow」仍可手动触发一次完整更新（含取数与提交）。

## 退出码

| 码 | 含义 | 处理 |
|---|---|---|
| 0 | 成功（含产物无变化） | 结束 |
| 4 | 发布前校验未通过，**未推送** | 读输出的校验错误，不要重试 |
| 3 | 产物已生成但提交/推送失败 | 通常是远端有新提交，重跑一次即可 |
| 2 | 运行异常 | 读输出定位，不要盲目重跑 |

## 硬性约束

- **不要加 `--snapshot`**。它用离线演示数据，会把线上页面覆盖成 `DEMO`。
- **不要手动提交** `web/index.html`、`web/analysis_packet.json`、`data/last_run.json`、
  `docs/持仓分析报告.md`、`data/packets/positions_packet.json`。
  它们都是生成产物，只由本命令产出，手动改动会和每日流水线冲突。
- **不要修改阈值、规则或 `config/` 下的参数**来让校验通过。校验未通过是要报告的问题，
  不是要绕过的障碍。
- 需要离线调试时用 `SKIP_PULL=1 bash scripts/daily.sh`，其余步骤不变。

## 持仓分析同步说明

持仓报告和数据包会随仓库公开发布，含持仓代码、份额、成本、浮动盈亏。
口令只从 `POSITIONS_PASSPHRASE` 环境变量读取，绝不写入任何文件。

没有该环境变量时自动跳过持仓分析，只更新市场页，退出码不受影响。
持仓分析单独失败时只告警，不阻断市场页更新。
