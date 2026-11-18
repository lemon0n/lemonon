#!/usr/bin/env bash
# 每日更新唯一入口：拉代码 → 装依赖 → 取数生成 → 发布前校验 → 提交推送。
#
#   bash scripts/daily.sh
#
# 可选环境变量：
#   PY=python3.12    指定解释器（默认 python3.11，找不到就用 python3）
#   SKIP_PULL=1      跳过 git pull（离线调试用）
#
# 退出码：0 成功 / 2 运行异常 / 3 提交推送失败 / 4 发布前校验未通过
set -uo pipefail

cd "$(dirname "$0")/.." || exit 2

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
  if ! git pull --rebase --autostash origin main; then
    die "拉取失败：请先处理本地未提交改动或分支分叉，再重跑"
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

# ---------- 4. 持仓分析（可选，需要口令） ----------
# 报告与数据包随同一次提交一起推送；没有口令就跳过，不影响市场页更新。
if [ -n "${POSITIONS_PASSPHRASE:-}" ] && [ -f web/positions.enc.json ]; then
  say "生成持仓分析报告"
  if ! "$PY_BIN" scripts/analyze_positions.py \
        --out docs/持仓分析报告.md \
        --packet data/packets/positions_packet.json; then
    printf '\n[警告] 持仓分析失败，本次只更新市场页，继续。\n' >&2
  fi
else
  say "跳过持仓分析（未设置 POSITIONS_PASSPHRASE）"
fi

# ---------- 5. 生成 + 校验 + 推送 ----------
say "取数并生成页面（实时源失败会自动降级）"
"$PY_BIN" scripts/run_update.py --json --push
code=$?

case "$code" in
  0) say "完成：页面已更新并推送" ;;
  4) printf '\n[失败] 发布前校验未通过，未推送。检查上面的校验错误。\n' >&2 ;;
  3) printf '\n[失败] 产物已生成但提交/推送失败。\n' >&2 ;;
  *) printf '\n[失败] 运行异常（退出码 %s）。\n' "$code" >&2 ;;
esac
exit "$code"
