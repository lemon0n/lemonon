# 中国 ETF 量化研究台

个人自用的 ETF 研究台：本地模型做研究决策，GitHub 只当托管 + Pages。

## 每天怎么用

默认 **agent 模式**（不需要模型服务，我来当那个模型）：

```bash
bash scripts/daily.sh                              # 抓数 + 冻结事实 + 出任务卡
#   读 <run_dir>/AGENT_TASK.md 与 context.json，写 agent_output.json
python3 scripts/run_research.py --finish --push    # 风控 + 报告 + 页面 + 推送
```

如果本机部署了模型服务：把 `config/llm.yaml` 的 `provider` 改成 `openai_compatible`，
之后 `bash scripts/daily.sh` 一条命令做完。

## 在线页面

[lemon0n.github.io/lemonon](https://lemon0n.github.io/lemonon/)

<details>
<summary>更多（部署 / 文档 / 持仓口令）</summary>

**持仓口令**（可选，未设置则只更新市场页）：

```bash
export POSITIONS_PASSPHRASE='你的口令'
bash scripts/daily.sh
```

口令只从环境变量读取，不写入仓库。设置后 `daily.sh` 会让本地模型生成一份
**深度持仓分析**（`docs/持仓分析报告.md`：每只的角色、因果链、支持证据、反证、失效条件、
目标权重与执行条件），并随仓库一起推送——**报告与数据包包含个人持仓、成本、份额，会随仓库
公开发布**，不接受公开就取消该环境变量。模型没跑成时自动回退到确定性版报告。

**部署**：GitHub Actions 只做 Pages 发布，不取数。数据由本机 `daily.sh` 生成并推送
`web/index.html`、`web/analysis_packet.json`、`data/last_run.json`（以及上面两份持仓文件）。
依赖：`python3.11 -m pip install -r requirements.txt`。

**本地模型**：OpenAI 兼容接口，默认 `http://127.0.0.1:11434/v1`（Ollama）。换地址/模型用
`export LLM_BASE_URL=... LLM_MODEL=...`，或直接改 `config/llm.yaml`；先跑
`python3.11 -m etfquant.llm.cli doctor` 确认连通。

**文档**：先看 [系统手册](docs/系统手册.md)（架构 / 分析口径 / 每日刷新 SOP / 验收与排查）；运行命令见 [AGENTS.md](AGENTS.md)；页面每块由谁产出见
[页面区块对照](docs/页面区块对照.md)；LLM 研究层见
[实施说明](docs/LLM研究决策层_实施说明.md)。历史设计与施工记录在
[docs/archive](docs/archive/README.md)，不参与每日运行。

**校验**：`python -m pytest -q`。模型不可用时状态 `LLM_FAILED`，页面不会用规则模板冒充研究结论。

</details>
