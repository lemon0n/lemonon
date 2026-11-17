# 中国 ETF 量化观察台

在线页面：[lemon0n.github.io/lemonon](https://lemon0n.github.io/lemonon/)

基于确定性规则的 ETF 市场观察与组合研究工具。生成的 `web/index.html` 是自包含页面。应用本身不调用 LLM、不自动交易；离线合成数据仅用于演示。

## 使用

```bash
python3.11 -m pip install -r requirements.txt
python3.11 scripts/run_update.py
python3.11 -m pytest tests/ -q
```

离线预览：`python3.11 scripts/run_update.py --snapshot`。结果标记为 `DEMO`，不可作为交易依据。

本机持仓分析示例：

```bash
POSITIONS_PASSPHRASE="$POSITIONS_PASSPHRASE" python3.11 scripts/analyze_positions.py \
  --out /tmp/持仓分析报告.md --packet /tmp/positions_packet.json
```

持仓报告和数据包可能包含个人资产信息，请保存在仓库外，不要提交或放入公开网页。口令仅通过环境变量提供。

## 指导文件

- 自动/手动市场数据运行与故障处理：[每日运行说明](docs/每日运行说明.md)
- 个人 LLM 每日持仓解读：[持仓分析每日运行指导](docs/持仓分析每日运行指导.md)，仅供你的个人 LLM/MCP 工作流使用，不会显示在 HTML
- 语料研究参考：[沉关河语料研究记录](docs/沉关河方法论蒸馏.md)，不是生产规则；生产规则只认 `config/methodology.yaml`
- 回测记录：[回测报告](docs/回测报告.md)，其中已撤回的旧结论不可引用

运行说明负责程序操作；持仓指导负责个人 LLM 解读；蒸馏文档仅记录语料研究。不要根据历史计划稿执行。