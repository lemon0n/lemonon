# 中国 ETF 量化研究台 · 系统全景说明

> 面向外部评审的单文件说明：项目做什么、怎么算、页面每块从哪来、代码怎么组织、数据文件怎么串、提示词与 skills 怎么接入。
> 读者不需要访问仓库即可理解全貌；需要核对时，文中的路径与函数名都能在仓库里对应到唯一位置。
>
> 版本：2026-11-24 · 代码规模：Python 约 11,000 行、前端 `app.js` 3,902 行、CSS 362 行、测试 174 项
> 每日入口：`bash scripts/daily.sh`（唯一）；开发排查：`docs/页面区块对照.md`（逐块细化到函数级）

---

## 0. 怎么读这份文档

| 你想了解 | 直接看 |
|---|---|
| 这是什么、边界在哪 | §1 |
| 整体架构与数据流 | §2 |
| 目录与每个文件的职责 | §3 |
| 每天那条命令做了什么 | §4 |
| 数据从哪来、断了怎么办 | §5 |
| 指标与规则怎么算（含公式） | §6–§10 |
| 页面怎么生成、每块内容 | §11–§13 |
| 提示词与 skills 怎么用 | §14 |
| 质量门禁与测试 | §15 |
| 哪些做了、哪些没做 | §16 |
| 关键取舍与风险 | §17–§18 |

---

## 1. 项目摘要

### 1.1 一句话

把**公开 ETF 行情**转成一份可复核的**仓位建议**（目标占比、差额、挂单价、份数、费用），
再用一个**单文件网页**呈现市场环境、组合结构、逐只分析与次日情景；
个人持仓只以密文形式存放，解密与盈亏计算全部发生在**浏览器本地**。

### 1.2 它做什么

- 取数：ETF 日线、实时价、指数日线、板块成交、宽基份额、市场广度/外盘/折溢价。
- 计算：均线、量比、突破四条、假突破、20/60 日波动、相对强弱、市场状态、结构评分。
- 决策：规则卡（11 条）求值 → 动作；目标仓位表 → 差额 → 挂单价/数量/费用。
- 呈现：市场概况（公开）、持仓分析（解锁后）、持仓设置。
- 发布：一条命令完成取数、生成、校验、提交、推送；GitHub Actions 只发布 Pages。

### 1.3 它不做什么（写死在代码与文档里）

| 不做 | 原因 / 表现 |
|---|---|
| 不自动下单 | 只输出挂单价与份数，标注「价格是执行价，不保证成交」 |
| 不预测点位、不给目标价 | 情景只写触发条件与对应动作，不写概率 |
| 不承诺收益、不写胜率 | 禁词表 12 条硬拦截（`config/brief_banned.txt`） |
| 不用离线合成数据出交易动作 | 合成数据 → 状态 `DEMO`，动作一律 `ABSTAIN` |
| 不把持仓上传 | 仓库只有 `web/positions.enc.json` 密文 |
| 不在数据不足时硬凑结论 | 缺项写「缺失/未覆盖/样本不足」，不估算填空 |

### 1.4 关键数字

| 指标 | 值 |
|---|---|
| 规则卡 | v2.0，11 条规则，5 种动作，4 个等级 |
| 观察池 | 4 只宽基 ETF（沪深300 / 中证500 / 科创50 / 创业板） |
| 单文件页面 | 约 320 KB，CSS/JS/数据全内联，双击可看 |
| 测试 | 174 项（Python + 前端 JS 抽取执行） |
| 数据源 | 东财 push2、腾讯 qt/ifzq、新浪 hq、上交所份额披露，全部公开免费 |

---

## 2. 架构总览

### 2.1 五层结构

```
┌─────────────────────────────────────────────────────────────────┐
│ L5 解释层   点评五段 / 逐只解读 / 市场洞察 / 缠论展示            │
├─────────────────────────────────────────────────────────────────┤
│ L4 执行层   目标 − 现仓 = 差额 → 动作 → 挂单价/份数/费用        │
├─────────────────────────────────────────────────────────────────┤
│ L3 组合层   结构评分 × 波动系数 → 单只目标权重（plan_v3）        │
├─────────────────────────────────────────────────────────────────┤
│ L2 结构层   月/周/日三层 + 相对强弱 + 双评分卡                   │
├─────────────────────────────────────────────────────────────────┤
│ L1 环境层   基准趋势/波动 → 市场状态 → 总仓位上限                │
├─────────────────────────────────────────────────────────────────┤
│ L0 数据层   实时源 → 失败降级 → 质量门 → 血缘标记               │
└─────────────────────────────────────────────────────────────────┘
```

三条传导纪律：

1. **额度只能收紧**：环境给总上限，板块与个股只能往下压，不能加。
2. **下层不许翻案**：结构再强，板块 D 级（上限 0）也不能加仓。
3. **解释层不许自创**：点评、个股卡、洞察的动作必须等于目标仓位表的结果。

### 2.2 运行拓扑

```
scripts/daily.sh
   │
   ├─ git pull ─ 依赖检查 ─（可选）持仓分析
   ├─ fetch_market_snapshot.py   广度/分布/外盘/折溢价 → data/snapshot/market.json
   ├─ fetch_national_team.py     上交所宽基份额     → data/national_team.json
   │
   └─ run_update.py --json --push
        │
        ├─ pipeline.run()
        │    ├─ loader：实时源 → 失败降级快照（逐通道标记）
        │    ├─ quality.check_bars()：日期/OHLC/根数/陈旧
        │    ├─ features.frame()：唯一指标实现
        │    ├─ relative_strength.compute()：同日基准超额
        │    ├─ market_regime.compute()：状态 + 仓位区间 + 位置赔率
        │    ├─ methodology.decide()：唯一动作求值
        │    ├─ pricing.prices()：执行价位口径
        │    ├─ plan_v3.build()：目标权重
        │    └─ webgen.build_data() + render()：内嵌数据 → 单文件 HTML
        │
        ├─ packet.write()：web/analysis_packet.json（权威结果）
        ├─ verify：run_id 同源 + 不变量复跑
        └─ git commit + push（只提交指定产物）
              │
              └─ GitHub Actions：仅发布 Pages（不重新取数）
```

### 2.3 前后端职责边界

| 职责 | 位置 | 原因 |
|---|---|---|
| 取数、指标、规则、目标权重、数据包 | Python（构建时） | 需要可复现、可测试、可回溯 |
| 持仓解密、市值/盈亏、差额→订单、页面渲染 | 浏览器（运行时） | 服务端与构建产物拿不到持仓 |
| 池外持仓的目标补算 | 浏览器 | 后端只认识观察池；日线在浏览器现取 |
| 缠论结构 | 浏览器 | 只做展示，不参与决策 |

> 结论：**同一套公式有两份实现**——Python `plan_v3` 与 JS `clientSignals/synthesizePlanTargets`。
> 二者按同一口径写，差异只在数据来源（后端缓存 vs 浏览器现取），并在页面上标明「池外补算」。

---

## 3. 目录与文件职责

```
.
├── AGENTS.md                    每日刷新唯一说明书（只指向 daily.sh）
├── README.md                    项目简介
├── requirements.txt             numpy/pandas/PyYAML + 可选 akshare/requests/cryptography
├── config/                      参数与规则（只改这里，不改代码）
│   ├── methodology.yaml         规则卡 v2.0：11 条规则 + 谓词白名单 + 动作语义
│   ├── risk.yaml                仓位区间、结构目标、组合硬约束、费用口径
│   ├── strategy.yaml            均线/量能/突破阈值、回测参数
│   ├── universe.yaml            观察池 4 只 ETF + 基准映射 + 报价精度
│   ├── sw_industry_map.json     申万二级 → 一级归并表（31 行业）
│   └── brief_banned.txt         点评禁词 12 条
├── contracts/
│   └── portfolio_decision.schema.json   组合决策契约（Python/JS 同形）
├── src/etfquant/
│   ├── config.py                读配置、路径常量、缓存目录
│   ├── universe.py              观察池与基准映射
│   ├── datasource/              取数层
│   │   ├── loader.py            统一入口 + 降级链 + 来源报告
│   │   ├── akshare_adapter.py   东财/腾讯/新浪真实源
│   │   ├── snapshot.py          离线快照读取
│   │   └── schema.py            日线列校验（MIN_BARS=30）
│   ├── features.py              指标唯一实现（生产/回测共用）
│   ├── indicators/              analyze()：特征 + 折溢价 + 状态文案
│   ├── quality.py               数据质量检查与状态合并
│   ├── signals/
│   │   ├── market_regime.py     市场状态 / 仓位区间 / 位置赔率 / 缺口
│   │   └── relative_strength.py 同日基准超额
│   ├── methodology.py           规则卡加载与唯一求值 decide()
│   ├── pricing.py               执行价位（回踩/反抽/支撑/阻力）
│   ├── portfolio/
│   │   ├── plan_v3.py           目标权重（页面唯一出口的上游）
│   │   ├── positions.py         资产分类与持仓解析
│   │   ├── execution.py         后端执行模拟
│   │   ├── analysis.py          报告专用 S1–S5（非页面）
│   │   └── decision/risk/opportunities/snapshot/watchlist
│   ├── packet.py                数据包构建、哈希、校验、归档
│   ├── webgen.py                组装 DASHBOARD + 渲染单文件 HTML
│   └── web_assets/
│       ├── app.js               全部页面逻辑（3,902 行）
│       ├── style.css            样式（362 行）
│       ├── rules.js             前端规则谓词镜像
│       └── decision.js          前端执行契约引擎
├── scripts/
│   ├── daily.sh                 每日唯一入口
│   ├── run_update.py            取数→生成→校验→提交推送
│   ├── fetch_market_snapshot.py 广度/分布/外盘/折溢价
│   ├── fetch_national_team.py   上交所宽基份额
│   ├── fetch_index_sector_weights.py 指数→申万一级权重
│   ├── analyze_positions.py     带口令的持仓报告（可选）
│   ├── gen_snapshot.py          离线演示快照生成器（固定日期）
│   ├── gen_page_demo.py         演示页生成器
│   ├── run_backtest.py          回测
│   └── compare_*.py             一次性对比脚本
├── skills/
│   └── portfolio-brief/SKILL.md 今日点评外部生成契约
├── skills_src/                  上游方法论技能（只借思路，不直接执行）
├── tests/                       174 项测试
├── data/
│   ├── snapshot/                离线快照（market.json、sector_flow.csv、日线、指数权重）
│   ├── cache/                   实时取数缓存
│   ├── national_team.json       宽基份额
│   ├── news_note.json           消息面 100 字解读
│   ├── last_run.json            运行清单
│   └── runs/                    历史数据包归档
├── web/
│   ├── index.html               线上页面（单文件，自动生成）
│   ├── analysis_packet.json     权威数据包
│   └── positions.enc.json       持仓密文
└── docs/                        设计、施工、验收、审计文档
```

---

## 4. 每日运行链路

### 4.1 一条命令

```bash
bash scripts/daily.sh
```

### 4.2 六步

| 步 | 动作 | 失败策略 |
|---|---|---|
| 1 | 切到 `main`，`git pull --rebase --autostash` | 冲突则中止并提示 |
| 2 | 找可用 Python（3.9+，优先已装依赖的），缺依赖则 `pip install` | 安装失败退出 2 |
| 3 | 若设置 `POSITIONS_PASSPHRASE`，跑 `analyze_positions.py` | 仅告警，不阻断 |
| 4 | `fetch_market_snapshot.py`：广度/分布/外盘/折溢价 | 仅告警，保留旧值 |
| 5 | `fetch_national_team.py`：宽基份额 | 仅告警，沿用上次 |
| 6 | `run_update.py --json --push` | 见退出码 |

### 4.3 退出码

| 码 | 含义 | 处理 |
|---|---|---|
| 0 | 成功（含产物无变化） | 结束 |
| 2 | 运行异常 | 读报错，不盲目重跑 |
| 3 | 产物已生成但提交/推送失败 | 原样再跑一次（自愈路径） |
| 4 | 发布前校验未通过，未推送 | 报校验原文，不改阈值绕过 |

### 4.4 产物

| 文件 | 内容 | 是否提交 |
|---|---|---|
| `web/index.html` | 单文件页面 | 是 |
| `web/analysis_packet.json` | 权威数据包 | 是 |
| `data/last_run.json` | 状态、数据日、降级明细、哈希 | 是 |
| `data/national_team.json` | 宽基份额 | 是 |
| `data/snapshot/market.json` | 市场快照（广度/外盘/折溢价刷新） | 是 |
| `docs/持仓分析报告.md`、`data/packets/positions_packet.json` | 持仓报告（仅当有口令） | 存在则同次提交 |

### 4.5 发布前校验（`run_update --verify`）

1. 三个产物存在；
2. `run_id` 在 packet / manifest / HTML 内嵌数据三者一致（同源）；
3. `input_hash` 在 manifest 与 packet 一致；
4. `packet.validate_packet()` 全部不变量通过；
5. 最近状态非 OK 时只记 warning。

### 4.6 盘中运行的口径

- 日线：`_drop_unclosed_today()` 在北京时间 15:05 前剔除当日未收盘 K 线。
- 实时价：只用于展示与市值，**不改日频信号**；前端 `legFeat()` 固定用刷新前的收盘价求值。
- 重复运行同输入：`run_id` 含输入哈希，动作应完全一致。

---

## 5. 数据层

### 5.1 数据源与降级链

| 通道 | 主源 | 兜底 1 | 兜底 2 | 最终兜底 |
|---|---|---|---|---|
| ETF 日线 | 东财 `fund_etf_hist_em` | 腾讯 `fqkline` | 新浪 `getKLineData` | 离线快照 |
| 实时价 | 东财 `fund_etf_spot_em`（含 IOPV） | 腾讯 `qt.gtimg.cn` | 新浪 `hq.sinajs.cn` | 离线快照 |
| 指数日线 | 腾讯 `fqkline` | 新浪 `getKLineData` | — | 离线快照 |
| 指数点位 | 新浪 `hq.sinajs.cn` | 日线收盘 | — | 保留快照 |
| 板块成交 | 东财 push2 `ulist`（31 个 BK） | 腾讯板块排行 | — | 离线快照 |
| 宽基份额 | 上交所 `commonQuery` | — | — | 保留上次 |

限流处理：东财 push2 被限流时**不重试**（重试会延长封禁），直接降级到腾讯/新浪。

### 5.2 通道标记与状态

`loader.source_report()` 输出每条通道的真实来源：

```python
channels = {'daily': {code: 'live'|'snapshot'}, 'spot': 'live'|'snapshot',
            'index_daily': {...}, 'sector': ..., 'market': 'snapshot'}
synthetic = 任一关键通道（daily/spot/index_daily）落到 snapshot
degraded  = 同上
```

状态合并优先级：`ERROR > ABSTAIN > DEMO > DEGRADED > OK`。

| 状态 | 含义 | 页面行为 |
|---|---|---|
| `OK` | 日线/实时价/基准全部真实 | 正常展示 |
| `DEGRADED` | 非关键字段缺失（无 IOPV、板块快照） | 展示 + 限制说明 |
| `ABSTAIN` | 关键数据缺失/陈旧/冲突 | 只给事实，不给动作 |
| `DEMO` | 用了离线合成快照 | 徽标提示，动作全部 ABSTAIN |
| `ERROR` | 运行或校验失败 | 保留上一份成功产物 |

### 5.3 质量门（`quality.check_bars`）

| 检查 | 失败结果 |
|---|---|
| 日期可解析、无重复、升序 | 阻断（ABSTAIN） |
| `high/low` 与 `open/close` 不矛盾 | 阻断 |
| 价格为正、成交量非负 | 阻断 |
| 根数 ≥ `MIN_BARS`（30） | 阻断 |
| 最后交易日距运行日 > 5 个自然日 | 阻断（陈旧） |
| 合成数据 | 只 warning，状态 DEMO |

### 5.4 三个日期

| 字段 | 来源 | 用途 |
|---|---|---|
| `meta.data_date` | 各腿最后一根已收盘日线 | 行情日，所有信号基准 |
| `meta.snapshot_date` | `market.json.as_of[:10]` | 人工快照日（情绪/快讯/政策） |
| `meta.as_of` / `run_date` | 运行时刻 | 仅记录 |

`snapshot_date ≠ data_date` 时，p1 顶部强制提示。
`fetch_market_snapshot.py` 只在**广度抓取成功**时才刷新 `market.as_of`——避免外盘或折溢价单独成功把旧情绪说成今天。

### 5.5 字段血缘

每个关键值都可回答「值多少、哪天的、谁给的、是不是合成」：
`quality.field()` 返回 `{value, as_of, source, ingested_at, is_synthetic, quality_flag}`；
数据包里逐腿记录 `data_status`、`data_date`、`quality_blocking`。

---

## 6. 指标层（`features.py`，唯一实现）

### 6.1 为什么只有一份

早期 `indicators/ma|volume|structure` 与 `backtest/engine.build_features` 各写一份，
上影线取「倒数第三根」还是「当日」不一致，导致同一形态在不同链路得到不同结论。
现在**所有派生特征只在 `features.frame()` 计算**，生产、页面、回测共用。

### 6.2 公式

| 指标 | 定义 |
|---|---|
| 均线 | `MA_n = close.rolling(n).mean()`，n ∈ {5,10,20,60,120} |
| 量比 | `volume / 前 5 日均量（不含当日）` |
| 放量 / 缩量 | 量比 ≥ 1.30 / ≤ 0.80（`config/strategy.yaml`） |
| 站上 MA5 天数 | 连续 `close > MA5` 的计数，遇 False 归零 |
| 连续低于 MA10 | 连续 `close < MA10` 的计数 |
| 20 日新低 | `close <= rolling(20).min(low)` |
| 突破四条 | ①不破关键位 ②明显缩量 ③慢跌快涨 ④有承接，各自可判定 |
| 假突破 | 放量 + 收盘下跌 + 收盘 < MA20 |
| 上影线 | **固定取倒数第三根** K 线，生产与回测同根 |
| 5/20 日收益 | `close / close.shift(n) − 1` |
| 20/60 日波动 | 日收益标准差 × √252 × 100（年化 %） |
| 均线缠绕 | 三线最大最小差 / MA20 < 1.2% |
| 位置 | `pos20 = (close − low20) / (high20 − low20)` |

### 6.3 代码骨架

```python
def frame(bars, cfg=None):
    st = (cfg or config.cfg())['strategy']
    c, h, l, o, v = (df['close'], df['high'], df['low'], df['open'], df['volume'])
    for p in st['ma']['periods']:
        out['ma%d' % p] = c.rolling(p).mean()
    out['vol_ratio'] = (v / v.rolling(5).mean().shift(1))     # 不含当日
    out['days_above_ma5'] = _consecutive((c > out['ma5']).fillna(False).values)
    out['below_ma10_2d'] = _consecutive((c < out['ma10']).fillna(False).values)
    out['true_breakout_count'] = out[['tb_hold_key','tb_shrink',
                                      'tb_slow_fast','tb_support']].sum(axis=1)
    out['false_breakout'] = (out['expand'] & (c < c.shift(1)) & (c < out['ma20']))
    out['upper_shadow_pct'] = ((h.shift(2) - np.maximum(o.shift(2), c.shift(2)))
                                / c.shift(2) * 100)            # 倒数第三根
    out['vol20'] = r.rolling(20).std() * np.sqrt(252) * 100
    return out
```

`last_dict()` 把最后一行转成纯 Python 字典，规则卡直接消费。

---

## 7. 规则层（`config/methodology.yaml` + `methodology.decide()`）

### 7.1 规则卡结构

```yaml
version: '2.0'
actions: {CLEAR: 清仓, TRIM: 分批减仓, ADD: 加仓, HOLD: 持有, WATCH: 观察}
levels:  {D: 风险退出, C: 减仓保利, A: 可加仓, B: 等待确认}

predicates:            # 谓词白名单：Python 与 JS 必须实现同一组
  below_ma10_days_gte: 连续收盘低于 MA10 的日数 >= N
  false_breakout: 放量下跌且收盘低于 MA20
  stand_back_days_gte: 收盘站上 MA5 且连续日数 >= N
  true_breakout: 突破四条全部满足
  is_20d_low: 收盘为 20 日新低
  always: 恒真（只允许最低优先级兜底）

rules:
  - id: R-D1
    level: D
    priority: 100
    when: {below_ma10_days_gte: 2}
    action: CLEAR
    text: 收盘连续低于 MA10 达 2 日
    rationale: {phen: ..., judge: ..., act: ...}
    exec: 次日以限价分笔卖出
```

- 未知谓词、重复 ID、非法动作 → **启动即失败**，不允许用 `always → HOLD` 掩盖配置错误。
- 规则名必须是可观测事实，不写「主力放弃 / 诱多 / 真出货」。

### 7.2 求值逻辑

```python
def decide(feat, data_status='OK', overrides=None):
    if data_status == 'ABSTAIN':        # 数据不足：禁止动作
        return dict(status='ABSTAIN', action='ABSTAIN', ...)
    if data_status == 'DEMO':           # 合成数据：只演示，动作 ABSTAIN
        r = match_rule(feat)
        return dict(status='DEMO', action='ABSTAIN', demo=..., ...)

    r = match_rule(feat)                # 按 priority 取第一条命中的规则
    if r is None:
        return dict(status='DEGRADED', action='ABSTAIN', ...)

    action, level = r['action'], r['level']

    # 组合层覆盖：只作用于 ADD
    if action == 'ADD':
        if pos > regime_hi:  ov = 'O-1'   # 超仓位区间 → 降为 HOLD
        elif pnl < -8:       ov = 'O-2'
        elif pnl > 30:       ov = 'O-3'
        if ov: action = 'HOLD'; blocked_by.append(ov)
    return dict(status='OK', level=level, action=action, rule_ids=..., hits=...)
```

关键设计：**规则决定「什么时候可以动」，目标仓位决定「动到多少」**。
两者不互相覆盖，因此不会出现「上面一套规则、下面一套技术」的双结论。

### 7.3 页面上的规则位置

| 位置 | 规则的作用 |
|---|---|
| 个股卡「结论」 | 引用目标仓位表的动作（不直接展示规则码） |
| 明细表「动作」 | 同上 |
| 点评「今天动什么」 | 同上 |
| 规则卡 | 只在数据闸门与最早减仓时点生效 |

---

## 8. 市场状态与相对强弱

### 8.1 市场状态（`signals/market_regime.py`）

只输入**基准指数日线**（默认沪深300），三个可观测维度：

| 维度 | 判据 |
|---|---|
| 趋势 | 收盘 vs MA60，且 MA5 vs MA20 |
| 波动 | 20 日年化波动 > 60 日 × 1.25 → 「波动抬升」 |
| 位置 | 近 120 日高低点、距高/低、上下空间比（赔率） |

状态与仓位区间（`config/risk.yaml`）：

| 状态 | 区间 | 目标中枢（plan_v3 取中值） |
|---|---|---|
| 上行趋势 | 80–90% | 85% |
| 震荡区间 | 60–70% | 65% |
| 下行趋势 | 30–40% | 35% |
| 下行 + 波动抬升 | 20–30% | 25% |
| 未知 | null | 默认 65%（不空仓） |

另外输出：`ma5/10/20/30/60/120`、均线缠绕间距、站上 MA5 天数、近 20 日未回补缺口（最多 3 个）、`position{high120, low120, odds, …}`。

> 判据只有两条：「收盘与 60 日线」「5 日线与 20 日线」。
> 波动抬升只是再降一档，不单独改变方向。

### 8.2 相对强弱（`signals/relative_strength.py`）

- 必须使用**同日**基准收盘；日期不一致 → `is_known=False`，标签写「未知」。
- `excess5 / excess20 = 标的收益 − 基准收益`。
- 状态：20 日新低且低于 MA10 → 「20日新低 · 弱于基准」；`excess5 > 0.5` 且站上 MA5 → 「强于基准」（有/无放量确认）；`|excess5| ≤ 0.5` → 「同步」；否则「弱于基准」。
- 缺失不得加分、不得出单。

---

## 9. 组合层（`portfolio/plan_v3.py`）

### 9.1 目标权重的完整公式

```
总上限 total = (fit_lo + fit_hi) / 2
单只基础 coef = (0.6 + 0.4 × 结构评分/100) × min(1, 15 / 20日年化波动)
候选按 coef 排序，取前 6 只
归一 denom = Σ coef(前 6)
单只目标 = min(25%, 评级上限, total × coef / denom)
```

结构评分（0–100）：

```
score = 50
      + 15（收盘 > MA20）/ −15（收盘 < MA20）
      + 10（MA5 > MA10 > MA20）/ −10（MA5 < MA10 < MA20）
      + 5 （收盘 > MA60）
      − 10（收盘 ≤ 20 日最低）
clamp 到 [0, 100]
```

评级与单只上限：

| 评级 | 分数 | 单只上限 |
|---|---|---|
| S | ≥85 | 25% |
| A | 75–84 | 20% |
| B | 60–74 | 10% |
| C | 50–59 | 5% |
| D | <50 | 3%（观察仓，不清零） |

附加输出：`tier`（跌破 MA30 可一次卖 / 跌破 MA20 先卖一半 / 跌破 MA10 只回目标 / 结构未坏只减一半）、`wk_up`（周线是否站上 20 周线）、`confirm`（0–3：站上 MA10、MACD 多头、连续 2 日量增价涨）。

### 9.2 板块上限

`plan_v3` 之后，前端 `rsPlanRows()` 再做一次压缩：

```
同一板块的目标合计 > 板块上限（S25/A20/B10/C5/D0）
→ 该板块内各只按比例缩放，不突破单只上限
```

### 9.3 池外持仓的目标补算（浏览器）

后端只认识观察池 4 只；持仓里的行业/债券/海外标的在浏览器补算，三级策略：

| 情况 | 处理 | 页面标记 |
|---|---|---|
| 能取到 ≥30 根日线 | 用与 `plan_v3` 相同的公式算分/评级/上限/目标 | 「池外补算 · 72 分 B 级」 |
| 日线不足 30 根 | 按类别结构目标折算（宽基 50 / 行业 25 / 债券 15 / 黄金 5 / 海外 5，乘总上限后同类均分） | 「结构参考目标」 |
| 类别也未知（未分类/货币） | 不给目标，动作写「暂不设目标」并说明缺什么 | 「—」 |

无日线时**不生成订单**；目标是参考值，动作固定「日线未到，暂不动」。

前端公式（`clientSignals()`）：

```js
score = 50
      + (last > ma20 ? 15 : -15)
      + (ma5>ma10 && ma10>ma20 ? 10 : (ma5<ma10 && ma10<ma20 ? -10 : 0))
      + (last > ma60 ? 5 : 0)
      - (last <= low20 ? 10 : 0)
volf = min(1, 15 / vol20)
coef = (0.6 + 0.4 * score / 100) * volf
target = min(25, cap(grade), total * coef / Σcoef)
```

---

## 10. 执行层（差额 → 动作 → 订单）

### 10.1 差额与动作（唯一口径）

```js
function planActionOf(gap, wkUp, confirm, belowMa10){
  if(gap == null)            return {action:'WAIT', text:'目标缺失'};
  if(Math.abs(gap) < 3)      return {action:'HOLD', text:'差额 x pct，未到 3pct，持有'};
  if(gap > 0){                          // 要加
    if(!wkUp)                return {action:'WAIT', text:'周线向下，不买'};
    if(confirm < 2)          return {action:'WAIT', text:'确认只有 n/3 条'};
    return {action:'ADD', text:'加仓 +x pct', pace:'分 2 批'};
  }
  if(!wkUp || belowMa10)     return {action:'TRIM', text:'减仓 x pct', pace:'50/30/20'};
  return {action:'TRIM', text:'先减一半差额', pace:'50/30/20'};
}
```

### 10.2 下单信息

```
挂单价：买 = 现价 × 1.0001，向上进位到 0.001
        卖 = 现价 × 0.9999，向下截断到 0.001
数量  ：floor(总资产 × 目标% ÷ 挂单价 ÷ 100) × 100
        买入不回退现有份额；买入受现金限制
本次操作：建议数量 − 现有数量
首批  ：卖出 |差额| × 50%，向下取整到 100 份（其余 30/20）
费用  ：max(5 元, 成交额 × 0.5bp) + 成交额 × 1bp
```

六条边界（都有明确文案，不出现 0 或假数字）：

| 情况 | 文案 |
|---|---|
| 目标缺失 | 「目标缺失」 |
| 价格缺失 | 「价格缺失」 |
| 差额不足 100 份 | 「不足一手」 |
| 买入现金不足 | 「受现金限制」（自动下调手数） |
| 当日成交额 < 0.1 亿 | 「流动性不足」 |
| 停牌 | 「停牌」 |

---

## 11. 数据包与契约

### 11.1 `web/analysis_packet.json`

| 分区 | 内容 |
|---|---|
| `status` / `run_id` / `generated_at` / `data_date` | 运行标识 |
| `config_hash` / `input_hash` / `code_version` | 可复现三元组 |
| `data_quality` | 覆盖率、合成字段、陈旧字段、冲突、阻断项、`market_snapshot` |
| `regime` | 状态、区间、基准日、观测条数 |
| `legs[]` | 逐只：`data_status`、`data_date`、观测、`signal_state`、`action`、`level`、`rule_ids`、反证、未知项、`quality_blocking` |
| `decisions[]` | 动作、理由、价位类型、约束 |
| `orders[]` | 公开观察池订单（页面持仓订单在浏览器生成，**此数组为空**） |
| `portfolio_after` | 组合后视图（公开版：不含个人持仓） |
| `validation` | 各项不变量结果 |

> 注意：`orders` 为空是设计，不是 bug——服务端拿不到个人持仓，订单只能在浏览器算。

### 11.2 哈希与同源

```
input_hash  = sha256(逐腿 {code, data_date, data_status})[:16]
config_hash = sha256(全部 config)[:16]
run_id      = 运行时刻 + '-' + input_hash
```

`run_update --verify` 用 `run_id` 校验 packet / manifest / HTML 内嵌数据同源。

### 11.3 契约文件

`contracts/portfolio_decision.schema.json` 定义 Python 与 JS 必须产出同一形状：
`meta / portfolio_before / market_context / holding_decisions / opportunities / orders / portfolio_after / validation / audit`。
只描述结构，不写阈值。

---

## 12. 页面层

### 12.1 生成方式

`webgen.render()` 把三样东西拼进 `SHELL` 模板：

```python
SHELL.replace('@@CSS@@', css)       # style.css
     .replace('@@DATA@@', payload)  # json.dumps(DASHBOARD)，< > 转义
     .replace('@@JS@@', rules_js + decision_js + app_js)
```

输出单个 HTML，无外部请求（除运行时行情 JSONP）。双击即可打开。

### 12.2 HTML 骨架

```html
<div class="app">
  <div class="top"> 品牌 / flash / 状态徽标 / 刷新行情 / 更新时间 </div>
  <div class="body">
    <div class="side"> 市场概况 · 持仓分析 · 持仓设置 </div>
    <div class="content">
      <div id="p1" class="page on"></div>
      <div id="p5" class="page"></div>
      <div id="p7" class="page"></div>
    </div>
  </div>
</div>
<div id="lock" class="lock on"> 口令 / 创建 / 选择文件 / 仅浏览 </div>
<script>window.DASHBOARD = {...};</script>
<script>/* rules.js + decision.js + app.js */</script>
```

### 12.3 `DASHBOARD` 数据结构

```json
{
  "meta":   {"data_date","snapshot_date","as_of","run_date","status","run_id",
             "source":{...},"skipped":[],"benchmark_date","dashboard_version"},
  "packet": {"schema_version","status","run_id","validation","data_quality","extras"},
  "market": {"as_of","indices","breadth","sentiment","rotation","distribution",
             "premium","valuation","glob","liquidity","macro","news","calendar",
             "news_sentiment","policy_heat","heat","flow","national_team","regime"},
  "legs":   [ {code,name,category,status,data_status,data_date,level,action,
               last,change,ma5,ma10,ma20,ma60,ma120,ma_state,vol_ratio,
               stand_back,shrink,false_breakout,true_breakout_count,
               support,reduce,rs,price,quality,evidence} ],
  "orders": [],
  "trading": {...}, "methodology": {...}, "targets": {...},
  "plan":   {"total_target","fit_lo","fit_hi","regime","gap_threshold",
             "top_n","max_single","items":[{code,name,score,grade,cap,
             target_weight,wk_up,confirm,tier,ma10,ma20,ma30,ma60}]},
  "brief":  null,
  "sector_weights": {"as_of","indices":{"000300":{...}},"etf_index":{"510300":"000300"}},
  "contract": {...}, "decision": null
}
```

### 12.4 渲染流程

```
window.load
  → D = window.DASHBOARD
  → render()            顶部徽标 + p1 + p5 + p7 三块同时生成
  → autoUnlock()        有会话口令则解密；否则弹锁屏
  → 解锁后 applyHold() → render() → ensureHoldQuotes() 补价格 → render()
  → page5() 内 setTimeout(rsInit, 0)
       ├─ rsRenderBrief / rsRenderSector / rsRenderMarket / rsRenderDetail
       ├─ fetchBars(每只持仓)  + rsFetchWeekly(每只持仓)
       └─ 全部回来 → rsAfterBars()：重算计划、刷新表格、点评、各块
```

### 12.5 隐私模型

```
口令 ──PBKDF2-SHA256（210,000 次，16B 盐）──▶ 256 位密钥
        └──AES-GCM（12B IV）──▶ 密文 {v, kdf, iter, salt, iv, ct}
```

- 仓库只有密文；构建机、GitHub、CDN 都拿不到明文。
- 口令只存 `sessionStorage`（关闭标签页失效）。
- 页面产物里没有任何持仓、成本、资金字段。

---

## 13. 页面逐块（内容 + 实现）

### 13.1 p1 市场概况（`page1()`）

| # | 区块 | 显示 | 数据 | 实现 |
|---|---|---|---|---|
| 1 | 快照日提示 | 快照日 ≠ 行情日时提示 | `meta.snapshot_date` | `page1()` |
| 2 | 四卡 | 成交额、情绪分、仓位区间、依据条数 | `breadth` / `sentiment` / `regime` | 同上 |
| 3 | 指数与均线 | 6 个指数：最新/涨跌/均线状态 | `market.indices` | `loader.indices()` |
| 4 | 状态与情绪 | 约 12 条情绪条目 | `sentiment.items` | 人工快照 |
| 5 | 阶段 → 仓位 → 我的持仓 | 联动条 + 四卡（目标/当前/差额/结论） | `plan` + `calcPort()` | `linkStrip()` / `planSection()` |
| 6 | 板块概况 | 折叠标题 + 热力图（面积=流通市值，颜色=涨跌） | `market.heat[]` | `squarify()` treemap |
| 7 | 国家队动向 | 最新一期合计份额/较上次/近四周 + 六类一段话 | `national_team.series` | `nationalTeamSection()` |
| 8 | 行业成交额与占比 | 行业、成交额、占比、涨跌、市值 | `market.flow[]` | — |
| 9 | 轮动与主线 / 涨跌分布 | 主线、落后、六档分布 | `regime` + `distribution` | — |
| 10 | 宏观环境四块 | 估值 / 外围 / 资金面 / 宏观数据 | `valuation/glob/liquidity/macro` | 人工快照 |
| 11 | 政策与消息面 | 快讯、日历、消息情绪（含 100 字解读）、政策热度 | `news/calendar/news_sentiment/policy_heat` | 解读来自 `news_note.json` |

### 13.2 p5 一、持仓概况

| 区块 | 显示 | 算法 |
|---|---|---|
| 四个数字 | 总资产、持仓市值、浮动盈亏、当日盈亏 | 盈亏 % 分母：浮盈 ÷ Σ成本；当日 ÷ Σ昨收市值；缺价/缺成本/缺昨收各自降级 |
| 今日点评 | 五段：今日基调 → 大盘与量能 → 结构 → 今天动什么 → 改判 | `rsBriefSections()`；每段先判断再给数字依据 |
| 明细表（12 列） | 名称/代码、板块、仓位现→目标、数量、本次操作、挂单价、费用、成本→现价、盈亏、5/20 上涨占比、全市场位置、动作 | 目标来自 `plan.items` 或池外补算；差额→动作→订单同一出口 |

点评优先读 `data/brief.json`（外部 skill 产出）；缺失或校验失败则用引擎现场生成。

### 13.3 p5 二、持仓分析

**1. 市场环境**

| 小块 | 内容 | 判读 |
|---|---|---|
| 大盘位置（七项） | 点位、均线排列、五均线开关、量能、缺口、空间、波动 | 判据只看「收盘 vs MA60」「MA5 vs MA20」；波动 >60 日×1.25 再降 10pct |
| 均线各自管什么 | 5/10/20/30/60/120 日 + 20 月线用途 | 折叠说明 |
| 热度与情绪 | 涨跌平、涨停跌停、成交额、恐慌、连续普跌、温度 | 只有放量急杀才算恐慌 |
| 资金动向 | 主力、两融、北向说明、过热板块（占比 ≥15%） | 北向说明「2024-08 起不再盘中披露」 |
| 隔夜与消息 | 外围 6 项、前 3 条快讯 | 只算开盘扰动 |

国家队已移出 p5，只在 p1 保留最新一期。

**2. 组合情况**

| 块 | 内容 |
|---|---|
| 组合板块结构 | 各行业暴露条（占持仓市值），≥25% 超配、≤5% 低配，未映射单列 |
| 集中度与结构 | 最大板块、前三合计、持有/有效只数（1÷HHI）、现金比例、TMT 合并（电子+计算机+通信） |
| 组合与市场是否一致 | 先给结论，再给：最大暴露是否主线、超低配清单、走弱但仍有暴露、覆盖度、轮动信号、未映射说明 |
| 申万板块健康度 | 评分、评级、板块上限、涨跌、成交占比、组合暴露、关系、状态 |

板块评分四维：

```
资金 25% = clamp(50 + (该行业成交占比 ÷ 31 行业均值 − 1) × 20, 0, 100)
政策 20% = policy_heat 中同名或互含主题的热度
情绪 15% = clamp(50 + 当日涨跌 × 8, 0, 100)
技术 40% = 未接入（缺行业代表 ETF 周线），按剩余权重归一
```

**3. 个股分析（九块）**

| 顺序 | 块 | 内容 |
|---|---|---|
| 1 | 结论 | 减/持/加 + 现→目标、差额、挂单价、费用 |
| 2 | 进场检查 | 三步 ✓/✗：不创新低、均线多头/实体阳线/站上 120 日、回踩不破/缩量/假突破 |
| 3 | 三周期 | 月线（20 月线）、周线 5/10/20/30、日线 5/10/20/60/120 + 量比 |
| 4 | 双评分卡 | 底部：月线底背离 25 + 倍量站上 20 月线 20 + 周线排列 15；顶部：月线顶背离 30 + 破 10 月线 20 + 周线死叉 15 + 板块过热 10 |
| 5 | 结构图 | K 线 + MA5/10/20 + 笔 + 中枢 + 成交量 + MACD；只画最近 220 根 |
| 6 | 缠论结构（展示层） | 中枢 ZG/ZD、现价在中枢上/中/下、最近一笔方向与幅度、底/顶背驰/三买；与目标的关系与冲突裁决 |
| 7 | 概率 | 5/20/60 日上涨占比、样本数、20 日中位；样本 <30 写「样本不足」 |
| 8 | 怎么做 | 现→目标、差额、确认条数、挂单价、首批、分批 |
| 9 | 改判 | 转好：站上 20 日线且周线转多；恶化：连续两日破 30 日线 → 卖出剩余差额 |

行情缺失时降级为「目标/评级/现价 + 原因 + 重新取行情按钮」，不臆造均线与结构图。

**缠论口径（简化实现，非严格级别递归）**：

```
分型：左右各 2 根的顶/底
笔  ：顶底交替，间隔 ≥4 根，幅度 ≥1.5%
中枢：最近 4 笔的 3 段重叠，ZG = min(各段高)，ZD = max(各段低)
背驰：价格创新低而 MACD DIF 抬高（底背驰）；创新高而 DIF 走低（顶背驰）
三买：价格 > ZG
```

缠论当前**只解释、不改目标与订单**；要变成加仓过滤器，须先按 `docs/缠论融合回测方案.md` 跑 A/B 并过门槛。

**4. 市场洞察及方向**

| 块 | 内容 |
|---|---|
| 今日定性 | 时段（盘前/盘中/午盘/盘后/周末）+ 偏多/偏空/震荡 + 三条依据 |
| 位置与赔率 | 近 120 日高低、距高/低、上下空间、赔率；注明「赔率只描述位置」 |
| 情绪与主线 | 涨停跌停、成交额、恐慌、连续普跌、情绪节点、主线三判据、温度 |
| 情景与触发 | 偏弱延续 / 震荡修复 / 转强确认，真实价位 + 当前距离 |
| 复盘对照 | 上次计划 vs 今天的目标与评级（本机快照，不是成交回报） |
| 新方向候选 | 板块 B 级以上、非持仓、近 5 日不弱于大盘、同类别一只、不含不碰名单 |

定性打分：状态 ±2、MA5/MA20 ±1、涨跌占比 ±1、情绪分 ±1；≥2 偏多、≤−2 偏空。
温度 = 情绪 40% + 涨跌家数 35% + 成交额分 15% + 趋势分 10%。

### 13.4 p7 持仓设置

| 区块 | 内容 |
|---|---|
| 工具栏 | 保存到云端 / 新增一行 / 导入导出 CSV / 改口令 / 清空 |
| 快速添加 | 代码、份额、成本 → 自动补名称与现价 |
| 编辑表 | 代码、名称、类别、份额、成本、现价、市值、权重、浮动盈亏 |
| 汇总 | 可用现金、总资产、总仓位与浮盈 |
| 直写云端（折叠） | 仓库 + fine-grained PAT（只存本机）；不配则走「复制密文 + GitHub 编辑」 |

---

## 14. 提示词与 Skills

### 14.1 两类 LLM 任务，约束不同

| 工作流 | 用途 | 约束 | 允许解释动作 |
|---|---|---|---|
| A 公开市场摘要 | 只总结公开行情 | 不得出现 `action`、价格、份数、胜率 | 否 |
| B 本机持仓解读 | 结合解密后的持仓 | 只能原样解释，不得修改任何字段 | 是 |

### 14.2 `skills/portfolio-brief`（今日点评契约）

- 输入：`web/analysis_packet.json`、`data/brief_inputs.json`（当次行情/板块/资金/持仓与目标仓位）。
- 输出：`data/brief.json`

```json
{
  "data_date": "2026-11-23",
  "conclusion": "一句话基调",
  "blocks": [
    {"k": "今天是什么日子", "v": "……", "refs": ["market.breadth", "market.glob"]}
  ]
}
```

硬性要求：

1. `data_date` 必须等于当次页面数据日，否则整份作废；
2. `blocks` ≥6 块，`k` 不重复，`v` 非空；
3. 覆盖七类：大盘位置、量能、空间赔率、行业主线、资金、宏观隔夜、自身组合；缺哪类写「缺」；
4. 推理顺序：今天什么日子 → 大盘阶段 → 主要矛盾 → 行业信号 → 资金背景 → 自身偏差 → 今天动什么 → 改判；
5. 每句结论带数字，且数字能在页面找到；
6. 动作只能引用目标仓位表；
7. 禁用 12 个词（注意风险/保持谨慎/密切关注/综合来看/整体合理/酌情处理/有望/可能上涨/保证/必涨/稳赚/胜率）；
8. 不预测点位、不给目标价；概率判断必须带样本量；
9. 结尾「价格是执行价，不保证成交。」

`webgen._brief()` 会校验日期、结构、禁词；任一失败即回退到页面引擎生成。

### 14.3 `data/news_note.json`（消息面 100 字解读）

```json
{"data_date": "2026-11-23", "note": "100 字以内的解读"}
```

要求：一段话、≤100 字、不列点、不用固定套话；说清正负面各来自哪条消息、对今天意味着什么；
拿不到材料就留空。日期必须等于快照日，否则页面不显示。

### 14.4 上游 skills（`skills_src/`，只借思路）

| Skill | 借用的部分 | 是否被代码直接调用 |
|---|---|---|
| `chenguanhe-perspective`（沉关河） | 分层顺序、结论先行的表达 | 否，提炼进规则卡与点评结构 |
| `a-share-turning-point` | 月/周/日三层、双评分卡、评分档→单只上限、20 月线 | 否，对应 `legScore()` 与评级分档 |
| `topnews` | 舆情/盘面情绪的结构化口径 | 否，对应 `market.json` 的人工快照字段 |
| `quant-backtest-strategy` | 成本口径、约束复核、数据边界写法 | 否，对应 `backtest/` 与 `config/strategy.yaml` |

> 仓库里没有「缠论 skill」；缠论只以代码形式存在（`rsChanOf` / `analysis/chan.py`）。

### 14.5 防幻觉的四道闸门

1. **结构校验**：`_brief()` 检查 JSON 结构与必填字段。
2. **日期校验**：`data_date` 不等于数据日 → 丢弃。
3. **禁词表**：命中 12 词之一 → 丢弃。
4. **数字可查**：`refs` 指向字段路径；页面同页可核。

再加一条流程约束：点评失败**不重算交易动作**，只回退到引擎文本。

---

## 15. 测试与质量门禁

### 15.1 测试分布（174 项）

| 文件 | 覆盖 |
|---|---|
| `test_methodology.py` | 规则卡加载、谓词白名单、优先级、唯一求值 |
| `test_data_quality.py` | 日期/OHLC/根数/陈旧/合成状态 |
| `test_datasource_contract.py` | 适配器列名与字段契约 |
| `test_market_regime.py` | 状态判据、均线、缺口、位置 |
| `test_plan_order.py` | 目标→差额→动作→订单六条边界、费用口径 |
| `test_calc_port.py` | 四卡分母、缺价/缺成本/缺昨收降级 |
| `test_leg_score.py` | 双评分卡（在 node 里跑抽取的 JS） |
| `test_sector_score.py` | 四维评分与缺项归一 |
| `test_sector_weights.py` | 指数权重结构与行业名合法性 |
| `test_brief.py` | 点评日期/结构/禁词校验 |
| `test_publish_guard.py` | 产物同源、run_id、哈希 |
| `test_backtest_no_lookahead.py` | 回测无前视 |
| `test_smoke.py` | 页面区块存在性、无密钥泄露 |
| 其余 | 分类、执行约束、风险桶、持仓读写、决策契约与黄金样本 |

### 15.2 门禁

| 门禁 | 命令 | 当前 |
|---|---|---|
| JS 语法 | `node --check src/etfquant/web_assets/app.js` | 通过 |
| Python 测试 | `python3 -m pytest tests -q` | 174 passed |
| 发布前校验 | `run_update.py --verify` | ok=true |
| 生成 | `run_update.py --json` | status=OK，validation ok |

---

## 16. 已实现 / 未实现（诚实矩阵）

### 16.1 已实现

| 能力 | 状态 |
|---|---|
| 实时日线（三源降级）、实时价、指数日线 | ✅ |
| 指标唯一实现、质量门、血缘标记 | ✅ |
| 规则卡 11 条 + 唯一求值 + 组合覆盖 | ✅ |
| 市场状态 → 仓位区间 → 目标权重 | ✅ |
| 差额→动作→订单（含六条边界） | ✅ |
| 相对强弱（同日基准）、板块评分、覆盖度 | ✅ |
| 单文件页面 + 本地解密 + 盈亏计算 | ✅ |
| 点评五段、洞察四块、复盘对照、候选 | ✅ |
| 池外持仓目标补算（日线→结构目标三级） | ✅ |
| 缠论展示层（中枢/笔/背驰/三买 + 与目标关系） | ✅ |
| 市场快照（广度/分布/外盘/折溢价） | ✅（沙箱网络受限时保留旧值） |
| 宽基份额、指数行业权重 | ✅（需联网跑） |

### 16.2 未实现 / 只做展示

| 项 | 状态 | 影响 |
|---|---|---|
| 板块技术面（行业代表 ETF 周线） | 未接入 | 四维评分永远「缺 1 项」 |
| 双评分卡中的估值/领先股/景气/资金/龙头 | 未接入 | 卡片标未接入项数 |
| 快讯/政策/日历/估值/宏观/资金面 | 人工快照 | 日期可能落后，顶部有提示 |
| 情绪分/连板/恐慌/连续普跌 | 人工快照 | 非实时计算 |
| 隔夜 A50 / 铜 | 未接入 | 外围只有 6 项 |
| 缠论进入执行链 | 未接入 | 需先跑 A/B 回测并通过门槛 |
| `data/brief.json` / `news_note.json` 自动生成 | 无执行器 | 缺失时点评走引擎、解读不显示 |
| 指南 4.2.5 纪律闸门 | 未单独成块 | 规则散落在个股卡与表下说明 |
| 板块快照自动刷新 | 无脚本 | `sector_flow.csv` 仍是演示快照 |

---

## 17. 关键设计决策

| 决策 | 原因 | 代价 |
|---|---|---|
| 动作只走一个出口（目标仓位表） | 旧版四套判断互相打架 | 规则卡只能管「最早减仓时点」 |
| 持仓只在浏览器解密与计算 | 服务端与产物拿不到持仓 | 订单无法进入 `analysis_packet.orders` |
| 池外持仓在浏览器补算目标 | 后端只认识观察池 | 同一公式两份实现，需对拍 |
| 数据不足一律 ABSTAIN | 避免用估算值出单 | 部分日子页面「没有动作」 |
| 缠论只做展示 | 没有样本外验证 | 用户可能觉得「没按缠论分析」 |
| 单文件 HTML | 双击可看、无构建依赖 | 文件 320 KB，内联重复 |
| 规则卡外置 YAML | 改参数不改代码、可审查 | 谓词需在 Python/JS 双实现 |
| 三日期分离 | 行情日 ≠ 人工快照日 ≠ 运行日 | 页面要额外提示，易被误读 |

---

## 18. 已知风险与后续

### 18.1 风险

| 风险 | 表现 | 缓解 |
|---|---|---|
| 免费行情源限流 | 东财 push2 断连 | 立即降级腾讯/新浪，不重试 |
| 人工快照过期 | 情绪/快讯落后两三周 | 顶部提示快照日；`as_of` 只在广度成功时刷新 |
| 板块快照是演示值 | 热力图与板块评分失真 | 计划接入 `fetch_sector_flow()` 进 daily |
| 两份目标公式漂移 | 池内/池外口径不一致 | 同一组常量 + node 测试；后续补对拍 |
| 缠论简化实现被误当结论 | 用户以为进入决策 | 卡片明写「展示层 · 不改动作」 |
| 日线 900 根上限 | 月线最多约 41 个月 | 足够 20 月线，但不足 60 月 |

### 18.2 建议的下一步（按优先级）

1. **P0** `as_of` 与分块日期：`market.json` 增加 `blocks_as_of`，顶部按块提示。
2. **P0** 板块快照接实时：复用 `akshare_adapter.fetch_sector_flow()`，加入 daily 与 PRODUCTS。
3. **P0** 行业权重进 daily：失败沿用并 `stale:true`。
4. **P1** daily 前置 `pytest`，测试红不推送。
5. **P1** 纪律闸门成块、`outlookConflicts()` 接线。
6. **P1** 板块技术面（行业代表 ETF 周线）。
7. **P2** 清理死函数（`friendlyIssues` / `renderPage5` / `rsRsi` 等）。
8. **P2** 缠论 Python/JS 对拍 + A/B 回测。

---

## 附录 A：常用命令

```bash
# 每日更新（唯一入口）
bash scripts/daily.sh

# 离线调试（不拉远端）
SKIP_PULL=1 bash scripts/daily.sh

# 带口令生成持仓报告
POSITIONS_PASSPHRASE='你的口令' bash scripts/daily.sh

# 只生成页面不推送
python3 scripts/run_update.py --json

# 只校验产物
python3 scripts/run_update.py --verify

# 测试
python3 -m pytest tests -q
node --check src/etfquant/web_assets/app.js

# 演示页（不碰线上产物）
python3 scripts/gen_page_demo.py
```

## 附录 B：字段速查

| 想找 | 字段 |
|---|---|
| 行情日 | `meta.data_date` |
| 快照日 | `meta.snapshot_date` |
| 运行状态 | `meta.status` |
| 总仓位上限 | `plan.total_target` |
| 仓位区间 | `plan.fit_lo` ~ `plan.fit_hi` |
| 单只目标 | `plan.items[].target_weight` |
| 评级 / 上限 | `plan.items[].grade` / `.cap` |
| 全市场位置 | `legs[].rs.excess5` / `.rs_label` |
| 板块权重 | `sector_weights.indices[idx][行业]` |
| ETF→指数 | `sector_weights.etf_index[code]` |
| 宽基份额 | `market.national_team.series[-1].groups` |
| 消息解读 | `market.news_sentiment.note` |
| 数据质量 | `packet.data_quality` |

## 附录 C：术语

| 用 | 不用 |
|---|---|
| 每只持仓 / 这只基金 | 腿、标的、leg |
| 目标仓位表 | 账本、ledger |
| 总仓位上限 | 锚、anchor |
| 评级 | 档位、level |
| 下单信息 | 单据、ticket |
| 数据不足，暂不判断 | ABSTAIN |
| 池外补算 | 临时估算 |
