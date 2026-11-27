# 每日刷新（唯一入口）

> 架构、每块分析口径、验收清单、故障排查：见 **[系统手册](docs/系统手册.md)**。
> 交给外部执行器（如 /workspace 的每日 runner）的完整指令：**[每日更新指令](docs/每日更新指令.md)**。
> 本文件只保留「今天要执行的命令」和硬规则。

先看 `config/llm.yaml` 的 `provider`，只有两种情况，别混用。

---

## A. agent 模式（默认）—— 我就是那个模型

不需要任何模型服务。**三条命令**：

```bash
bash scripts/daily.sh                       # ① 抓数 + 冻结事实 + 出任务卡（打印 run_dir）
#   ② 读 <run_dir>/AGENT_TASK.md 与 context.json，写 <run_dir>/agent_output.json
bash scripts/daily.sh --finish --push       # ③ 风控 + 订单 + 报告 + 页面 + 推送
bash scripts/daily.sh --status              # 随时查看 data/last_run.json 摘要
```

（`daily.sh` 内部就是调 `scripts/run_research.py --prepare/--finish`；直接用 python 命令也等价。）

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
| 机器可读状态 | `bash scripts/daily.sh --status`，或 `data/last_run.json`（status/data_date/levels/action_count/validation） |

---

## 硬规则（违反即失败，不是建议）

1. 引用的 `evidence_id` 必须出现在 `context.evidence_catalog` 里；一条都不引用也判失败。
   **例外**：本次没有任何可交易标的（未加载持仓）时允许零引用 —— 此时计划是「空仓 + 现金 100%」，
   用 `proposal.evidence` 引用 `market:regime` 说明等待理由即可；一旦有标的，规则立即恢复。
2. 权重是占含现金总资产的比例（0–1 小数），`sum(target_weight) + cash_target_weight = 1`。
3. 方向与权重必须一致（BUY/ADD 抬、SELL/REDUCE 降、EXIT 归零、HOLD 不动）。
4. 风控退回就改建议，**不要**放宽 `config/risk_policy.yaml` 来让它通过。
5. 不要手改 `data/runs/*/06_final_plan.json`、`data/research_latest.json`（改了无法重放）。
6. 模型/代理不可用时状态就是 `LLM_FAILED`，页面不会用规则模板冒充研究结论。
7. **行情日期必须与运行日比对**：来源即使是 live，日期早于预期交易日也按降级处理；
   页面、报告、`last_run.json` 与提交说明必须写真实行情日期，不得标「实时」。
8. **只收尾最新 prepare**：`--finish` 不带 run-dir 时只读 `.pending_run`，缺输出就报错，禁止回退旧日期；brief 必须绑定当前 run_id。
9. **没有离线快照**：`daily.sh` 每次跑 `fetch.py --market --national --sector --news`；抓不到就显示失败，禁止沿用旧值。
   快讯只来自本次抓取；行业权重只用今天抓的，失败指数不映射；brief 必须绑定当前 run_id。

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

---

## 收工前验收（30 秒）

1. `python -m pytest -q` → 全绿（当前 290 项）。
2. 打开 `web/index.html`：
   - 三个标签在：市场概况 / 持仓分析 / 持仓设置；
   - 持仓分析是「一、持仓概况 → 二、持仓分析 → 三、市场洞察」；
   - 个股卡三个选项卡能切换，「结构与图」里有 K 线与图例。
3. 对账：总资产 = 持仓市值 + 现金；目标合计 + 现金 = 100%；页面现价 = 明细表现价。
4. 数据日：`data/last_run.json` 的 `data_date` 是**实际行情日期**，`run_date` 是运行日；
   `data_stale=true` 时页面必须标「行情截至 X · 非实时」，`degraded=true`、`source.live=false`。

完整清单与排查方法见 [系统手册 §7.4–§9](docs/系统手册.md)。

---

## 延伸阅读

- [系统手册](docs/系统手册.md)：架构 / 分析口径 / 每日 SOP / 验收与排查（**先看这个**）
- [数据新鲜度审计](docs/数据新鲜度审计.md)：旧快照误用路径、修复边界与每日检查
- [页面区块对照](docs/页面区块对照.md)：每一块由哪个函数生成（开发索引，口径以手册为准）
- [LLM 研究决策层实施说明](docs/LLM研究决策层_实施说明.md)：四段研究、风控与订单的实现细节
- [docs/archive](docs/archive/README.md)：历史设计与施工记录，不参与每日运行
