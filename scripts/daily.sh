#!/usr/bin/env bash
# 每日更新唯一入口：拉代码 → 装依赖 → 取数生成 → 发布前校验 → 提交推送。
#
#   bash scripts/daily.sh                 # 全流程（openai 模式）或「抓数+冻结事实」（agent 模式）
#   bash scripts/daily.sh --finish --push # agent 模式第二步：写 agent_output.json 后收尾并推送
#   bash scripts/daily.sh --status        # 只读 data/last_run.json，打印今日运行摘要
#
# 可选环境变量：
#   PY=python3.12    指定解释器（默认 python3.11，找不到就用 python3）
#   SKIP_PULL=1      跳过 git pull（离线调试用）
#   RESEARCH=0       跳过 LLM 研究层，只更新确定性页面（默认按 config/llm.yaml 判断）
#   LLM_BASE_URL / LLM_MODEL / LLM_API_KEY  覆盖本地模型地址与模型名
#   POSITIONS_PASSPHRASE  持仓口令（可选；未设置时只做市场层，属正常）
#
# 退出码：0 成功 / 4 校验或风控未通过（不要重试）/ 3 提交推送失败（可重跑一次）/ 2 运行异常
set -uo pipefail

cd "$(dirname "$0")/.." || exit 2

# ---------- 0. 参数 ----------
MODE=run
EXTRA=()
case "${1:-}" in
  --status) MODE=status ;;
  --finish) MODE=finish; shift; EXTRA=("$@") ;;
  -h|--help)
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 0 ;;
  "") ;;
  *) printf '\n[失败] 未知参数：%s（可用 --finish [--push] / --status）\n' "$1" >&2; exit 2 ;;
esac

say() { printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$1"; }
die() { printf '\n[失败] %s\n' "$1" >&2; exit "${2:-2}"; }

# ---------- 1. 解释器 ----------
# 逐个真实探测：pyenv 的 shim 可能「存在但不可执行」，只看 command -v 会误判。
# 优先选已装好必需依赖的解释器，避免在只读环境里反复安装。
CANDS=()
for c in "${PY:-}" python3.11 python3.12 python3.13 python3 python; do
  [ -n "$c" ] || continue
  command -v "$c" >/dev/null 2>&1 || continue
  "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1 \
    || continue
  case " ${CANDS[*]-} " in *" $c "*) continue ;; esac
  CANDS+=("$c")
done
[ "${#CANDS[@]}" -gt 0 ] || die "找不到可用的 Python 3.9+，请先安装 Python 3.11"

# 必需依赖（akshare / requests / cryptography 缺失只会降级，不阻断）
NEED='import numpy, pandas, yaml'
PY_BIN=''
for c in "${CANDS[@]}"; do
  if "$c" -c "$NEED" >/dev/null 2>&1; then PY_BIN="$c"; break; fi
done

# ---------- 1.5 只读状态（不拉代码、不装依赖） ----------
if [ "$MODE" = "status" ]; then
  for c in "${CANDS[@]}"; do
    if "$c" -c 'import json,sys; sys.exit(0)' >/dev/null 2>&1; then
      "$c" - <<'PY'
import json, os
p = os.path.join('data', 'last_run.json')
if not os.path.exists(p):
    print('{"error": "data/last_run.json 不存在，说明还没跑过 finish"}')
    raise SystemExit(0)
d = json.load(open(p, encoding='utf-8'))
keep = ('ok', 'status', 'data_date', 'run_date', 'expected_data_date',
        'data_stale', 'quote_dates', 'stale_assets', 'degraded', 'synthetic',
        'levels', 'level_count', 'action_count', 'orders', 'fallback',
        'validation', 'run_id', 'html')
out = {k: d.get(k) for k in keep}
out['source_live'] = (d.get('source') or {}).get('live')
print(json.dumps(out, ensure_ascii=False, indent=2))
PY
      exit 0
    fi
  done
  printf '\n[失败] 找不到可用的 Python，读不了 last_run.json。\n' >&2
  exit 2
fi

# ---------- 2. 同步代码 ----------
if [ "${SKIP_PULL:-0}" != "1" ]; then
  if ! git remote | grep -q .; then
    die "当前目录没有 git remote，无法同步"
  fi
  BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
  if [ "$BRANCH" != "main" ]; then
    # 分支不对时先切回 main，否则产物会提交到错误的线上分支
    say "当前在 $BRANCH，切换到 main"
    git rev-parse --verify --quiet refs/heads/main >/dev/null \
      || die "本地没有 main 分支，请先 git fetch origin main"
    git checkout main >/dev/null 2>&1 \
      || die "切换到 main 失败：可能有未提交改动，请先处理后再重跑"
  fi
  say "拉取远端 main"
  # -X ours：冲突时保留远端版本。远端产物与本地产物同源同流程，取哪份等价；
  # 这样即使每日流水线刚提交过页面，也不会把仓库留在 rebase 冲突状态。
  if ! git pull --rebase -X ours --autostash origin main; then
    git rebase --abort >/dev/null 2>&1
    die "拉取失败：远端与本地改动冲突，请手动处理后重跑"
  fi
fi

# ---------- 3. 依赖 ----------
if [ -z "$PY_BIN" ]; then
  for c in "${CANDS[@]}"; do
    if "$c" -m pip --version >/dev/null 2>&1; then PY_BIN="$c"; break; fi
  done
  [ -n "$PY_BIN" ] || die "没有可用的 Python 且无 pip，请先安装依赖：pip install -r requirements.txt"
  say "安装依赖（$("$PY_BIN" -V 2>&1)）"
  "$PY_BIN" -m pip install -q -r requirements.txt || die "依赖安装失败"
  "$PY_BIN" -c "$NEED" >/dev/null 2>&1 || die "依赖仍不完整，请手动检查环境"
fi

say "使用解释器 $("$PY_BIN" -V 2>&1)"

# ---------- 3.3 agent 模式第二步：收尾（+ 推送） ----------
if [ "$MODE" = "finish" ]; then
  say "收尾：证据校验 → 确定性风控 → 订单 → 报告 → 页面"
  "$PY_BIN" scripts/run_research.py --finish "${EXTRA[@]}"
  code=$?
  case "$code" in
    0) say "完成：页面已刷新${EXTRA[*]:+（参数：${EXTRA[*]}）}" ;;
    4) printf '\n[失败] 校验或风控未通过（退出码 4），不要重试；按提示改建议后重跑。\n' >&2 ;;
    3) printf '\n[失败] 产物已生成但推送失败（退出码 3），通常远端有新提交，可重跑一次。\n' >&2 ;;
    *) printf '\n[失败] 运行异常（退出码 %s），不要盲目重试。\n' "$code" >&2 ;;
  esac
  exit "$code"
fi

# ---------- 3.5 研究模式 ----------
# agent 模式：没有模型服务，研究由「正在操作这个仓库的代理模型」完成。
# 这里只做到「抓数 + 冻结事实 + 出任务卡」，剩下的两步交给代理。
PROVIDER="$("$PY_BIN" - <<'PY' 2>/dev/null
import sys
sys.path.insert(0, 'src')
try:
    from etfquant.llm import policy
    print(policy.settings().get('provider', 'agent'))
except Exception:
    print('agent')
PY
)"
if [ "$PROVIDER" = "agent" ]; then
  say "agent 模式：抓数并冻结事实（研究由代理完成）"
  "$PY_BIN" scripts/fetch.py --market --national \
    || printf '\n[警告] 部分抓取失败，沿用上次快照。\n' >&2
  "$PY_BIN" scripts/run_research.py --prepare
  code=$?
  if [ "$code" != "0" ]; then
    printf '\n[失败] prepare 失败（退出码 %s）。\n' "$code" >&2
    exit 2
  fi
  say "下一步：读任务卡写 agent_output.json，然后执行"
  say "  bash scripts/daily.sh --finish --push"
  exit 0
fi

# ---------- 4. 持仓数据（可选，需要口令） ----------
# 深度持仓分析由研究层产出（docs/持仓分析报告.md）；RESEARCH=0 时才走确定性版。
if [ -n "${POSITIONS_PASSPHRASE:-}" ] && [ -f web/positions.enc.json ]; then
  if [ "${RESEARCH:-1}" = "0" ]; then
    say "生成持仓分析报告（确定性版）"
    "$PY_BIN" scripts/analyze_positions.py \
      --out docs/持仓分析报告.md \
      --packet data/packets/positions_packet.json \
      || printf '\n[警告] 持仓分析失败，本次只更新市场页，继续。\n' >&2
  else
    say "持仓分析交给研究层（深度版：角色/证据/反证/失效条件）"
  fi
else
  say "跳过持仓分析（未设置 POSITIONS_PASSPHRASE）"
fi

# ---------- 5. 生成 + 校验 + 推送 ----------
say "抓取市场快照与宽基份额（失败沿用上次快照，不阻断主流程）"
if ! "$PY_BIN" scripts/fetch.py --market --national; then
  printf '\n[警告] 部分抓取失败，本次沿用旧快照。\n' >&2
fi

say "取数并生成页面（实时源失败会自动降级）"
RESEARCH_ARG=""
if [ "${RESEARCH:-1}" = "0" ]; then
  RESEARCH_ARG="--no-research"
  say "RESEARCH=0：本次跳过 LLM 研究层"
fi
"$PY_BIN" scripts/run_update.py --json --push $RESEARCH_ARG
code=$?

# 研究层没产出深度报告时（模型离线/超时），回退确定性版，别让今天没有持仓分析
if [ -n "${POSITIONS_PASSPHRASE:-}" ] && [ "${RESEARCH:-1}" != "0" ]; then
  if ! find docs/持仓分析报告.md -mmin -15 2>/dev/null | grep -q .; then
    say "研究层未产出持仓报告，回退确定性版"
    "$PY_BIN" scripts/analyze_positions.py \
      --out docs/持仓分析报告.md \
      --packet data/packets/positions_packet.json \
      || printf '\n[警告] 回退生成也失败；今天的持仓报告保持上次内容。\n' >&2
  fi
fi

case "$code" in
  0) say "完成：页面已更新并推送" ;;
  4) printf '\n[失败] 发布前校验未通过，未推送。检查上面的校验错误。\n' >&2 ;;
  3) printf '\n[失败] 产物已生成但提交/推送失败。\n' >&2 ;;
  *) printf '\n[失败] 运行异常（退出码 %s）。\n' "$code" >&2 ;;
esac
exit "$code"
