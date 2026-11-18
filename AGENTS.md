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
3. `scripts/run_update.py --json --push` —— 实时取数、计算、生成页面、发布前校验、
   提交并推送 `web/index.html`、`web/analysis_packet.json`、`data/last_run.json`；
4. 打印状态、数据日、降级明细。

推送后 GitHub Actions 会自动部署 Pages，通常几分钟内生效。

## 退出码

| 码 | 含义 | 处理 |
|---|---|---|
| 0 | 成功（含产物无变化） | 结束 |
| 4 | 发布前校验未通过，**未推送** | 读输出的校验错误，不要重试 |
| 3 | 产物已生成但提交/推送失败 | 通常是远端有新提交，重跑一次即可 |
| 2 | 运行异常 | 读输出定位，不要盲目重跑 |

## 硬性约束

- **不要加 `--snapshot`**。它用离线演示数据，会把线上页面覆盖成 `DEMO`。
- **不要手动提交** `web/index.html`、`web/analysis_packet.json`、`data/last_run.json`。
  它们是生成产物，只由本命令产出，手动改动会和每日流水线冲突。
- **不要修改阈值、规则或 `config/` 下的参数**来让校验通过。校验未通过是要报告的问题，
  不是要绕过的障碍。
- 需要离线调试时用 `SKIP_PULL=1 bash scripts/daily.sh`，其余步骤不变。

## 持仓分析（不在本流程内）

持仓分析含个人资产信息，不进入公开仓库，也不由本命令生成。需要时单独执行：

```bash
POSITIONS_PASSPHRASE="$POSITIONS_PASSPHRASE" python3.11 scripts/analyze_positions.py \
  --out /tmp/持仓分析报告.md --packet /tmp/positions_packet.json
```

解读方法见 [持仓分析每日运行指导](docs/持仓分析每日运行指导.md)；
故障处理细节见 [每日运行说明](docs/每日运行说明.md)；
生产规则只认 `config/methodology.yaml`。
