# Golden 样例约定

本目录存放 `portfolio_decision` 的黄金样例（输入 → 期望输出），用于：

1. 固定 Python 决策契约的形状与关键数值；
2. 浏览器运行时（`src/etfquant/web_assets/decision.js`）与 Python 逐字段对拍；
3. 防止后续改动无意中改变订单、份额、费用或执行后仓位。

## 目录

- `portfolio_decision/*.json`：单个样例，结构如下
  - `name`：样例名
  - `input`：`legs` / `snap` / `cfg` / `regime` 四个键，均为可直接传给 `portfolio.execution.plan` 的最小结构
  - `expect`：期望的 `decisions` 关键字段、`orders`、`violations`、`portfolio_after`

## 规则

- 期望值以 Python 实现为唯一 oracle，生成后人工复核一次再入库；
- 样例只覆盖决策与执行层，不包含真实持仓、口令或令牌；
- 任何改变期望值的改动必须在变更摘要中说明原因。

## 现有样例

见 `portfolio_decision/` 目录。新增样例请同时补进 `tests/test_decision_golden.py` 的参数化列表。
