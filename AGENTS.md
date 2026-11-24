# 每日刷新（唯一入口）

先看 `config/llm.yaml` 的 `provider`，只有两种情况，别混用。

---

## A. agent 模式（默认）—— 我就是那个模型

不需要任何模型服务。**三条命令**：

```bash
python3 scripts/run_research.py --prepare                       # ① 抓数 + 冻结事实 + 出任务卡
#   ② 读 <run_dir>/AGENT_TASK.md 与 context.json，写 <run_dir>/agent_output.json
python3 scripts/run_research.py --finish --push                 # ③ 风控 + 订单 + 报告 + 页面 + 推送
```

`--prepare` 成功后会直接打印 `run_dir`、任务卡路径、输出路径和下一步命令，照抄即可。

**② 要写的东西**：`agent_output.json`，四个键 `research / proposal / redteam / revision`，
字段清单在 `AGENT_TASK.md` 里（由 pydantic 模型自动生成，不会过期）。

**被风控退回时**：`--finish` 会打印 `SINGLE_WEIGHT` 之类的违规明细；
改完写 `<run_dir>/agent_repair.json`（一个 RevisedProposal），再跑一次 `--finish`。

> `--prepare` 已经做过取数，`--finish` 复用同一份快照，不会重新抓一遍数据。

---

## B. 有本地模型服务 —— `provider: openai_compatible`

```bash
bash scripts/daily.sh
```

一条命令：拉代码 → 装依赖 → 抓数 → 生成页面 → 四段研究 → 风控 → 报告 → 推送。
模型地址写在 `config/llm.yaml`，或 `export LLM_BASE_URL=... LLM_MODEL=...`。

---

## 看结果

| 想看什么 | 在哪 |
|---|---|
| 持仓深度分析（逐只：角色/因果链/反证/失效条件/目标权重） | `docs/持仓分析报告.md` |
| 今天该不该动、风控改了什么 | `data/runs/<日期>/<run>/report.md` |
| 网页（GitHub Pages） | `web/index.html` → `lemon0n.github.io/lemonon` |
| 机器可读状态 | 命令最后一行 JSON：`status` / `data_date` / `validation.ok` |

---

## 硬规则（违反即失败，不是建议）

1. 引用的 `evidence_id` 必须出现在 `context.evidence_catalog` 里；一条都不引用也判失败。
2. 权重是占含现金总资产的比例（0–1 小数），`sum(target_weight) + cash_target_weight = 1`。
3. 方向与权重必须一致（BUY/ADD 抬、SELL/REDUCE 降、EXIT 归零、HOLD 不动）。
4. 风控退回就改建议，**不要**放宽 `config/risk_policy.yaml` 来让它通过。
5. 不要手改 `data/runs/*/06_final_plan.json`、`data/research_latest.json`（改了无法重放）。
6. 模型/代理不可用时状态就是 `LLM_FAILED`，页面不会用规则模板冒充研究结论。

> **研究范围**由 `config/llm.yaml → research.scope` 决定，默认 `holdings`：只看你自己的持仓，
> `config/universe.yaml` 的公开观察池不参与研究，也不能据此新建仓。
> 需要"持仓 + 候选池"时改成 `holdings+watchlist`。

---

## 持仓口令（可选）

有持仓才需要。二选一，**不要**写进仓库：

```bash
export POSITIONS_PASSPHRASE='你的口令'          # 方式一：环境变量
echo '你的口令' > positions/.passphrase          # 方式二：本地文件（positions/ 已 gitignore）
```

设了之后 `docs/持仓分析报告.md` 才会包含你的持仓；没设就只做市场层研究。
注意：该报告与 `data/packets/positions_packet.json` **会随仓库公开发布**，不接受就取消口令。
