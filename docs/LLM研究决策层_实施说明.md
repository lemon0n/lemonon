# LLM 研究决策层：实施说明

本文件说明本仓库如何落地《ETF LLM 交易分析系统详细执行书》（下称「执行书」），
以及**与原规则系统（v3/v4）的关系**。看完这份说明，不需要读执行书全文也能运行、排查与交接。

一句话概括这次升级：**规则从「决定交易」降级为「基线证据」，LLM 成为研究与交易建议的主体，
确定性风控决定建议能不能执行，账户原值不出本机。**

---

## 1. 职责边界（谁决定什么）

| 层 | 模块 | 能做什么 | 不能做什么 |
|---|---|---|---|
| 取数与指标 | `src/etfquant/datasource`、`features.py`、`quality.py` | 取数、清洗、复权、指标、数据质量状态 | 不做投资判断 |
| 规则基线 | `methodology.py`、`portfolio/plan_v3.py` | 输出动作/评分/目标权重，作为**证据** | 不再是最终动作，不再垄断结论 |
| 冻结事实 | `llm/context.py`、`llm/evidence.py` | 生成 `context.json` 与证据目录、快照哈希 | 不调用模型，不做判断 |
| LLM 研究 | `llm/pipeline.py` + `prompts/` | Research → Proposal → Red Team → Revision | 不能突破风控、不能编造数据、不能绕过证据 |
| 确定性风控 | `llm/risk.py` | 批准 / 退回修复 / 拒绝 / 降级 | 不静默改权重，不改投资观点 |
| 订单与报告 | `llm/orders.py`、`llm/report.py` | 差额订单草案、研究日报、**深度持仓分析** | 不连券商；报告不新增结论 |
| 页面与接口 | `web_assets/research.js`、`llm/api.py` | 展示五块内容、只读接口 | 不持有模型密钥，不在前端重算建议 |

**硬规则（执行书 1 / 22 章）**：Red Team 与 Revision 不得删除；模型不可用时状态必须是
`LLM_FAILED`；不允许把规则模板包装成新的模型建议。

**两种报告**（同一个 `FinalPlan` 渲染，数字同源）：

| 文件 | 回答什么问题 | 何时生成 |
|---|---|---|
| `data/runs/<日期>/<run>/report.md` | 今天该不该动、风控改了什么 | 每次研究运行 |
| `docs/持仓分析报告.md` | 我手里每一只到底在赌什么、什么情况算我错了 | 有持仓且模型产出计划时；失败回退确定性版 |

---

## 2. 一次运行产出什么

```
data/runs/<trade_date>/<HHMMSS>_<hash8>/
├── manifest.json        输入哈希、模型名、提示词版本、耗时、token、状态
├── context.json         冻结的事实快照 + evidence_catalog（研究全程只读）
├── 01_research.json     模型研究
├── 02_proposal.json     模型原始交易建议
├── 03_redteam.json      反方审查
├── 04_revised.json      修订后的建议
├── 05_risk.json         风控结果（修复后会覆盖为最终一次）
├── 06_final_plan.json   最终批准/拒绝计划（页面与报告唯一读取）
├── orders.json          订单草案（仅 APPROVED 时生成）
├── report.md            研究报告
├── 07_memory.json       本轮写入的研究记忆
├── logs.jsonl           每步耗时/用量/错误
└── prompts/*.md         本次实际使用的提示词快照
```

`data/runs/`、`data/ledger/`、`data/research_latest.json` 都在 `.gitignore` 里：
这些文件含权重与账户上下文，属于本地事实，不进公开仓库。

---

## 3. 四段式调用与修复循环

```
数据质量门 ──不合格──▶ ABSTAIN（只做数据诊断，不调用模型）
     │OK / DEGRADED
     ▼
① Research（研究：市场状态、资产角色、因果链、反证、情景、焦点问题）
     ▼
② Portfolio Manager（目标权重 + 现金 + 方向 + 优先级 + 执行条件）
     ▼
③ Red Team（只找问题：证据、时间尺度、重复暴露、成本、一致性）
     ▼
④ Revision（逐条接受或驳回，重新平衡权重；不得加入新事实）
     ▼
确定性风控 ──NEEDS_REPAIR──▶ Repair（模型按自己的优先级修，最多 max_llm_repairs 次）
     │APPROVED / REJECTED
     ▼
订单草案（仅 APPROVED）+ 报告（风控之后）+ 页面载荷（脱敏）
```

每一步输出都过证据校验：引用不存在的 `evidence_id` 直接判失败并重试一次；
连续不合格 → `LLM_FAILED`。

---

## 4. 权重与数字口径（最容易出错的地方）

| 场景 | 口径 | 例子 |
|---|---|---|
| context / domain / 风控 / 订单 | 占**含现金总资产**的比例 | `0.24` 表示 24% |
| 页面载荷 | 百分数（仅展示） | `24.00%` |
| 报告 | 百分数 + 与最终 JSON 同值 | `24.00%` |
| 类别权重 | 占含现金总资产 | 与 `risk.yaml` 的 `max_category_weight_pct` 同分母 |
| 金额 | 人民币元，只出现在本地账本 | 不进页面、不进公开文件 |

`HOLD/WAIT` 的目标权重必须等于当前权重；模型漏写的已持仓资产由系统补 `HOLD`
并写入 `system_adjustments`（这是数据补全，不是改变投资方向）。

---

## 5. 风控检查项（`llm/risk.py`）

| 代码 | 严重度 | 含义 |
|---|---|---|
| `DATA_NOT_EXECUTABLE` / `DATA_DEGRADED` | FATAL | 数据不合格/降级时不允许出可执行建议 |
| `UNKNOWN_SYMBOL` | FATAL | 标的既不在观察池也不在持仓 |
| `WEIGHT_SUM` | REPAIRABLE | 目标权重 + 现金 ≠ 1 |
| `CASH_FLOOR` / `GROSS_EXPOSURE` | REPAIRABLE | 现金低于下限 / 总仓位超上限 |
| `SINGLE_WEIGHT` / `CATEGORY_WEIGHT` / `MAX_LEGS` | REPAIRABLE | 单只/类别/腿数超限 |
| `TURNOVER` | REPAIRABLE | 单日换手超限 |
| `TRADE_BELOW_BAND` | REPAIRABLE | 变化小于不换仓带，应改 HOLD |
| `MISSING_EXECUTION_RULE` | REPAIRABLE | 没有条件式执行规则 |
| `MISSING_HELD` / `CURRENT_WEIGHT_MISMATCH` | REPAIRABLE | 漏持仓 / 当前权重与快照不一致 |

`config/risk_policy.yaml` **不得比 `config/risk.yaml` 更宽松**；`policy.consistency_issues()`
会逐项比对，`tests/test_llm_policy.py` 守住这条线。

---

## 6. 订单与报告

订单（`llm/orders.py`）：
- 目标权重 × 净值 ÷ 参考价 → 按 100 份向下取整；差额才下单；
- 先卖后买；卖出不超过可卖份额；买入金额+费用不超过「现金 + 卖出净回款」；
- 现金不足**不自动等比缩小**，相关买单标 `SUPPRESSED_NO_CASH` 交回人看；
- 金额低于最小交易额 → `SUPPRESSED_MIN_VALUE`；价格数据日与快照不一致 → `REJECTED_NOT_TRADABLE`；
- 参考价不等于成交价，报告里必须写清。

报告（`llm/report.py`）：
- 默认**确定性渲染**：所有数字来自 `06_final_plan.json`，不可能与计划不一致；
- 可选 LLM 撰写（`config/llm.yaml → report.use_llm`）：写完要过「数字回查」，
  任何一个数字在最终 JSON 里找不到就整篇退回确定性报告；
- 报告必须披露：模型最初想做什么 → 风控发现什么 → 模型怎么改 → 最终批准什么。

**深度持仓分析**（`render_positions` → `docs/持仓分析报告.md`）：
- 组合层：持仓合计、现金权重、回撤、前三集中度、类别暴露、模型识别的组合风险、风控结论；
- 逐只：角色 / 倾向 / 期限 / 观点 / 因果链（≥2 步）/ 支持证据 / 反证 / 「什么情况算我错了」/
  现权重 → 目标权重 → 动作 → 优先级 → 执行条件 / 观测事实（5·20 日收益、距 MA20/MA60、波动、超额）;
- 与规则基线不一致时会明确标注；模型没覆盖的持仓标「系统补 HOLD」；
- 模型未产出计划时**不覆盖**旧报告，由 `daily.sh` 回退确定性版 `analyze_positions.py`。

---

## 7. 持仓分析页的模型结论（`web_assets/research.js`）

页面只有三个标签页：市场概况 / 持仓分析 / 持仓设置。
模型结论不再单独占一页，而是并进「持仓分析」页顶部（`#portfolio-research`），五块内容：

1. **模型核心判断**：本次与上次相比发生了什么（含情景与数据限制）；
2. **原始模型建议**：反方与风控介入之前，模型最初想做什么；
3. **反方审查与修订**：反方发现的问题、模型接受与驳回的批评；
4. **最终批准计划**：风控结论、违规明细、最终要动的仓位、订单草案状态；
5. **改判跟踪**：今日焦点问题 + 历史观点与失效条件。

脱敏：页面只显示**权重百分比**与动作，不显示净值、现金、份额、金额。
真实份数仍在用户解锁持仓后由浏览器按现有 `orderTicket()` 口径计算。
`publish.no_absolute_fields()` 与 `tests/test_llm_page.py` 守住这条线。

> **隐私边界**：权重百分比会随页面一起公开（页面是 GitHub Pages 静态文件）。
> 只有在设置了 `POSITIONS_PASSPHRASE`、研究层能读到持仓时才会出现持仓权重；
> 设 `RESEARCH=0` 可完全跳过研究层。页面会在有持仓时显示这条提示，不做隐含披露。

---

## 8. 怎么运行

两种研究通道，由 `config/llm.yaml` 的 `provider` 决定：

**A. agent 模式（默认）**：不需要任何模型服务，研究由「正在操作这台机器的代理模型」完成。

```bash
bash scripts/daily.sh                               # 抓数 + 冻结事实 + 出任务卡
#   读 <run_dir>/AGENT_TASK.md 与 context.json，写 <run_dir>/agent_output.json
python3.11 scripts/run_research.py --finish --push   # 证据校验 → 风控 → 订单 → 报告 → 页面 → 推送
```

被风控退回时写 `<run_dir>/agent_repair.json` 再 `--finish` 一次。

**B. 有本地模型服务**：`provider: openai_compatible`，`bash scripts/daily.sh` 一条命令跑完。

```bash
# 依赖（LLM 层需要 pydantic；其余依赖不变）
python3.11 -m pip install -r requirements.txt

# 只跑研究层（不推送）
python3.11 scripts/run_research.py --json
python3.11 scripts/run_research.py --mock --no-page   # 不联网：用 mock 回放自查链路

# 诊断 / 重放 / 报告 / 接口
python3.11 -m etfquant.llm.cli doctor
python3.11 -m etfquant.llm.cli replay --run-dir data/runs/2026-11-24/143005_ab12cd34
python3.11 -m etfquant.llm.cli report --run-dir <dir> [--llm]
python3.11 -m etfquant.llm.cli api --port 8008
```

环境变量：

| 变量 | 作用 |
|---|---|
| `LLM_BASE_URL` | 仅 `openai_compatible` 模式：覆盖模型地址 |
| `LLM_MODEL` | 仅 `openai_compatible` 模式：覆盖模型名 |
| `LLM_API_KEY` | 本地服务通常不需要 |
| `RESEARCH=0` | 本次跳过研究层（B 模式下生效） |
| `POSITIONS_PASSPHRASE` | 解本机持仓（也可写入 `positions/.passphrase`）；没有就只做市场研究 |

配置里 `provider: openai_compatible` 只允许连本地地址（`127.0.0.1` / `localhost`）；
`provider: mock` 只能配合脚本客户端，运行结果标记 `LLM_MOCK`，**永不生成可执行订单**。

### 仓库结构（只记这四条）

| 目录 | 放什么 | 参与每日运行 |
|---|---|---|
| `scripts/` | `daily.sh`、`fetch.py`、`run_update.py`、`run_research.py`、`analyze_positions.py` | 是 |
| `src/etfquant/` | 取数（`datasource/`）、指标、规则基线、页面打包、`llm/` 研究层 | 是 |
| 	ools/ | 一次性/研究性工具（回测入口、明文预览页生成） | 否 |
| `docs/` | 在用的 5 份说明；历史设计与施工记录在 `docs/archive/` | 否 |

数据抓取已合并成一个入口：`scripts/fetch.py [--market] [--national] [--sector] [--all]`，
内部按任务隔离，任一失败只记录失败原因（不沿用旧值），不会中断页面更新。

---

## 9. 失败与降级（执行书 0.4）

| 情况 | 系统行为 |
|---|---|
| 数据 `DEMO` / `ABSTAIN` / `ERROR` | 直接 `ABSTAIN`，不调用模型，不生成订单 |
| 模型服务离线 / 超时 | 数据与页面照常更新，研究状态 `LLM_FAILED`，不出新订单 |
| 模型输出不是合法 JSON | 最多一次格式修复（不改内容），仍失败则 `LLM_FAILED` |
| 引用不存在的证据 | 带反馈重试一次，仍失败则 `LLM_FAILED` |
| 风控退回且修复后仍超限 | `REJECTED`，保留原始建议与违规明细 |
| 页面没有研究载荷 | 明确写「研究层没有可用结果」，**不用规则模板冒充** |

只展示本次 run_id 的研究；旧日期或旧运行一律不展示（用户只保留最新分析）。

---

## 10. 测试与验收

```bash
python3.11 -m pytest tests/ -q
```

新增（`tests/test_llm_*.py`）覆盖执行书第 17 章：

| 文件 | 覆盖点 |
|---|---|
| `test_llm_domain.py` | 方向与权重自洽、禁止多余字段、情景概率 |
| `test_llm_evidence.py` | 快照哈希稳定、证据目录、引用校验 |
| `test_llm_context.py` | 口径转换、焦点问题触发、裁剪顺序 |
| `test_llm_risk.py` | 每条硬约束可触发、补全 HOLD、政策不放松 |
| `test_llm_orders.py` | 取整、费用下限、可卖上限、现金不足、过期价格 |
| `test_llm_pipeline.py` | 四段链、修复循环、`LLM_FAILED`、`ABSTAIN`、证据重试、记忆 |
| `test_llm_no_lookahead.py` | T+1 K 线与回撤不得进入 context；报告数字回查 |
| `test_llm_repeat.py` | 连续 5 次相同快照不交易、不换词 |
| `test_llm_page.py` | 五块齐全、载荷无金额、无研究时明确说明 |
| `test_llm_positions_report.py` | 深度持仓分析：逐只角色/反证/基线分歧、无持仓时的降级 |
| `test_llm_cli.py` / `test_llm_integration.py` | doctor/replay/api、确定性层到研究层的接缝 |

另有执行书 27 章的五个情景（模型应真正改变交易 / 反对基线 / 承认旧观点错误 /
无实质变化 / 正确但风控不允许）以 `test_llm_pipeline.py` + `test_llm_risk.py` 的组合覆盖。

---

## 11. 与旧系统的映射（执行书 24 章）

| 旧模块 | 现在的位置 |
|---|---|
| 多源行情与降级 | 保留：`market_data`/`loader` → context 的 `quality` |
| 未收盘剔除、状态机 | 保留：数据质量门（不合格即 `ABSTAIN`） |
| 均线/波动/相对强弱 | 保留为证据：`assets[].features` |
| 10 条规则 | 降级为 `quant_baseline`（模型可支持或反对） |
| 市场状态 | 作为 `market.regime_baseline`，模型独立复核 |
| `plan_v3` 目标仓位 | 作为基线建议，不再直接成为最终目标 |
| 前端池外补算、板块压缩 | 移出浏览器：进入 context 与风控 |
| 双评分/概率/缠论 | 研究证据，不直接改权重 |
| 本机持仓解密 | 保留：`positions.load()` 只在本地读 |
| 单文件 HTML | 保留：模型结论并进「持仓分析」页顶部 |
| 规则文本点评 | 仅作故障诊断，不冒充模型建议 |

---

## 12. 仍然没做的

- 券商接口、实时盘口与成交回报（第一阶段只出草案，执行书 1.10）；
- 交易日历驱动的调度（仍由 `daily.sh` 手动/定时触发）；
- 三组 A/B 评估（规则 / 原始模型 / 风控后模型）需要至少 30 个交易日的历史回放；
- 板块技术面、个股资金流等原本就缺的数据源不变。
