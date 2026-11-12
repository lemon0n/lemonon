# 中国 ETF 量化观察台

在线地址：**https://lemon0n.github.io/lemonon/**

一个轻量的公开 ETF 观察工具：跑一次，产出一个**自包含页面** `web/index.html`（CSS / JS / 数据全部内嵌），双击即可打开，不需要本地服务。

> 注意：持仓解密依赖浏览器 WebCrypto，只在 **https / localhost** 下可用。直接双击 `file://` 打开时只能看公开行情，持仓页无法解锁。

> 页面打开时要求输入口令，解锁后才显示持仓分析 / 持仓设置。持仓以 **AES-256-GCM 密文**保存在 `web/positions.enc.json`，密钥由口令经 PBKDF2-SHA256 派生，解密只在你本机浏览器完成；仓库与页面里没有明文持仓。口令不写入仓库、不上传，忘记无法找回。观察池在 `config/universe.yaml` 里公开维护。
>
> 录入：在「持仓设置 → 快速添加」填代码、份额、成本价，点「保存到云端」。不想每次跳转 GitHub 的话，在「直写云端」里粘贴一次 fine-grained PAT（仅本仓库 `Contents: Read and write`，只存本机浏览器），之后一键写入；不填令牌则自动复制密文并打开 GitHub 编辑页，粘贴提交即可。Agent / CI 需要读持仓做分析时，用环境变量传口令：
>
> ```bash
> POSITIONS_PASSPHRASE='口令' python3 scripts/positions_crypto.py \
>   --decrypt web/positions.enc.json --out /tmp/positions.json
> ```
>
> 持仓明文只存在于内存，不写 localStorage、不进产物；同一标签页刷新免重输，关掉标签页后需重新输入口令。

## 运行

```bash
python3.11 -m pip install -r requirements.txt

python3.11 scripts/run_update.py            # 实时取数 → 重写 web/index.html
python3.11 scripts/run_update.py --snapshot # 不联网，用离线快照（自测 / 断网时用）
python3.11 scripts/run_update.py --push     # 生成后自动 commit + push 到 GitHub
python3.11 scripts/run_update.py --strict   # 任一关键通道降级即退出码 1（适合 CI 报警）
python3.11 -m pytest tests/ -q              # 22 项测试，不触网
```

退出码：`0` 正常 · `1` 严格模式下发生降级 · `2` 运行异常 · `3` 推送失败。

> **用本机 IP 取数 → 自动回填 GitHub**：免费行情接口对云机房 IP（GitHub Actions）限流更凶，本机家宽 / 办公网往往能直连。本地跑 `--push` 可一次完成「取数 + 生成 + 提交 + 推送」。浏览器里点「刷新行情」无法回填仓库——那需要把 GitHub Token 放在前端，等于公开泄露。

## 自动更新

`config/schedule.yaml` 定义了三层，任选其一或并用：

| 方式 | 触发 | 说明 |
|---|---|---|
| agent 每日定时 | 每天 07:30（北京时间） | 主通道，执行 `python3 scripts/run_update.py` |
| agent 按需 | 随时说一句 | 同一命令 |
| GitHub Actions | cron + 手动 | 兜底通道；UTC 23:30 = 北京 07:30，周一至周五盘前 |

Actions 流程：跑测试 → 实时生成 → 提交 `web/index.html` 与 `data/last_run.json` → 归档 artifact → 部署 GitHub Pages（仓库需公开并开启 Pages）。

## 页面「刷新行情」

顶部右侧的 **刷新行情** 按钮用免费 JSONP 接口（腾讯 `qt.gtimg.cn`，失败切新浪 `hq.sinajs.cn`）拉取最新价与涨跌幅，并即时重绘页面。

它只更新**价格**。折溢价、均线、分诊等级、参考价位依赖日线，需要重跑 `scripts/run_update.py`；按钮提示里已写明。

## 数据口径与降级

三层免费接口兜底，任一失败自动切换，不中断主链路：

| 通道 | 主 | 兜底 1 | 兜底 2 | 最终 |
|---|---|---|---|---|
| ETF 日线 | 东财 `fund_etf_hist_em` | 腾讯 `web.ifzq.gtimg.cn` | 新浪 `getKLineData` | 离线快照 |
| 实时价 | 东财 `fund_etf_spot_em` | 腾讯 `qt.gtimg.cn` | 新浪 `hq.sinajs.cn` | 离线快照 |
| 板块（31 申万一级） | 东财 `ulist.np/get` | 腾讯板块排行 `rank/pt/getRank` | — | 离线快照 |
| 指数点位 / 均线 | 新浪实时 + 新浪日线 | — | — | 保留快照旧值 |
| 宏观 / 资讯 / 日历 / 估值 | 离线快照（每项带可点击来源链接） | — | — | — |

- **硬降级**（`degraded: true`）：日线或实时价退回快照，价格不可信，`--strict` 判失败。
- **软降级**（`premium_ok: false`）：价格真实但兜底源无 IOPV，折溢价显示「数据不可用」且不参与打分。

东财 push2 有速率限制，触发后**立即放弃、不重试**（重试会把封禁从 5 分钟拉长到 40 分钟）。

所有接口均为免费公开 HTTP 端点，零 token、零注册；属非官方授权接口，无 SLA、字段可能随源站改版变化。

## 目录

```
config/         universe（公开观察池）/ strategy / risk / schedule
data/snapshot/  离线快照（日线、spot、板块、market.json、基准收益）
data/last_run.json  最近一次运行清单
src/etfquant/   datasource / indicators / signals / portfolio / orders / webgen
scripts/        run_update（唯一入口）/ gen_snapshot / run_backtest
web/            index.html ← 唯一交付物
.github/workflows/daily.yml   每日 07:30 + 手动触发 + Pages 部署
tests/          pytest（22 项，含无密钥 / 无明文持仓护栏）
```

## 边界

不接券商交易接口、不做盘中轮询 / websocket、不实时监控、不代客理财、不承诺盈利。
