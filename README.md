# 中国 ETF 量化观察台

在线页面：[lemon0n.github.io/lemonon](https://lemon0n.github.io/lemonon/)

基于确定性规则的 ETF 市场观察与组合研究工具。生成的 `web/index.html` 是自包含页面。
离线合成数据仅用于演示。

v5 起新增 **LLM 研究决策层**：规则输出降级为基线证据，由本地模型完成
Research → Proposal → Red Team → Revision 四段研究并直接给出目标权重，
再经确定性风控批准/退回/拒绝。实现与接缝说明见
[LLM 研究决策层实施说明](docs/LLM研究决策层_实施说明.md)。

- 模型不可用时不生成新建议（状态 `LLM_FAILED`），页面不会用规则模板冒充研究结论；
- 账户原值只留在 `data/runs/`（已 gitignore），页面只显示权重百分比；
- 第一阶段只产出订单草案，不连接任何券商。

## 使用

```bash
python3.11 -m pip install -r requirements.txt
python3.11 scripts/run_update.py --no-research     # 只跑确定性页面
python3.11 scripts/run_research.py                 # 只跑 LLM 研究层
python3.11 -m pytest tests/ -q
```

离线预览：`python3.11 scripts/run_update.py --snapshot`。结果标记为 `DEMO`，不可作为交易依据。

本机持仓分析（需要口令环境变量）：

```bash
POSITIONS_PASSPHRASE="$POSITIONS_PASSPHRASE" python3.11 scripts/analyze_positions.py \
  --out docs/持仓分析报告.md --packet data/packets/positions_packet.json
```

设置了 `POSITIONS_PASSPHRASE` 时，`scripts/daily.sh` 会自动生成这两份文件，并与市场页产物一起提交推送。
**报告与数据包包含个人持仓、成本、份额，会随仓库公开发布**；不接受公开就取消该环境变量。
口令本身只从环境变量读取，不写入仓库。

## 指导文件

**日常更新只执行这一条命令**（唯一入口，详见 [每日更新执行说明](AGENTS.md)）：

```bash
bash scripts/daily.sh
```

其余文档是背景资料，不改变执行方式：

- LLM 研究决策层（四段链、风控、订单、页面五块、测试）：[实施说明](docs/LLM研究决策层_实施说明.md)
- 自动/手动市场数据运行与故障处理：[每日运行说明](docs/每日运行说明.md)
- 个人 LLM 每日持仓解读：[持仓分析每日运行指导](docs/持仓分析每日运行指导.md)，仅供你的个人 LLM/MCP 工作流使用，不会显示在 HTML
- 语料研究参考：[沉关河语料研究记录](docs/沉关河方法论蒸馏.md)，不是生产规则；生产规则只认 `config/methodology.yaml`
- 回测记录：[回测报告](docs/回测报告.md)，其中已撤回的旧结论不可引用

运行说明负责程序操作；持仓指导负责个人 LLM 解读；蒸馏文档仅记录语料研究。不要根据历史计划稿执行。