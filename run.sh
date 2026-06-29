#!/usr/bin/env bash
# Era Champion Scanner — 一键运行脚本
# 用法:
#   ./run.sh                      # 扫描全部候选池 + 发飞书
#   ./run.sh --tickers NVDA MU    # 指定股票
#   ./run.sh --no-feishu          # 不发飞书
#   FEISHU_BOT_WEBHOOK=xxx ./run.sh  # 覆盖 webhook
#
# Cron 示例（周一至周五 美东 09:15 = 北京 21:15）:
#   15 21 * * 1-5 /Users/milongwu/Projects/workspace/EraChampionScnner/run.sh >> /Users/milongwu/Projects/workspace/EraChampionScnner/logs/cron.log 2>&1
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

export PYTHONUNBUFFERED=1
export PATH="${HOME}/miniforge3/bin:${HOME}/miniconda3/bin:/opt/homebrew/bin:/usr/local/bin:${PATH:-}"

# ── conda 配置 ──────────────────────────────────────────────
CONDA_ENV_NAME="erachampion"
CONDA_BIN=""

if command -v conda >/dev/null 2>&1; then
  CONDA_BIN="$(command -v conda)"
elif [ -x "$HOME/miniconda3/bin/conda" ]; then
  CONDA_BIN="$HOME/miniconda3/bin/conda"
elif [ -x "$HOME/miniforge3/bin/conda" ]; then
  CONDA_BIN="$HOME/miniforge3/bin/conda"
elif [ -x "$HOME/anaconda3/bin/conda" ]; then
  CONDA_BIN="$HOME/anaconda3/bin/conda"
fi

# ── 日志 ────────────────────────────────────────────────────
mkdir -p logs output
LOG="logs/erascanner.log"
NOW="$(date '+%Y-%m-%d %H:%M:%S')"

{
  echo "============================================================"
  echo "[INFO] 扫描开始: ${NOW}"
  echo "[INFO] 参数: $*"
} >> "$LOG"

# ── 运行 ─────────────────────────────────────────────────────
set +e
if [ -n "$CONDA_BIN" ]; then
  "$CONDA_BIN" run -n "$CONDA_ENV_NAME" python scanner.py "$@" 2>&1 | tee -a "$LOG"
else
  echo "[WARN] 未找到 conda，使用系统 python3" | tee -a "$LOG"
  python3 scanner.py "$@" 2>&1 | tee -a "$LOG"
fi
EXIT_CODE=$?
set -e

# ── 失败时也发飞书告警 ────────────────────────────────────────
if [ "$EXIT_CODE" -ne 0 ]; then
  FEISHU_WEBHOOK="${FEISHU_BOT_WEBHOOK:-}"
  FAIL_MSG="❌ 时代主角扫描器运行失败（${NOW}）\n退出码: ${EXIT_CODE}\n请检查日志: ${PROJECT_DIR}/${LOG}"
  PAYLOAD="$(python3 -c "import json,os; print(json.dumps({'msg_type':'text','content':{'text':os.environ['M']}},ensure_ascii=False))" M="$FAIL_MSG" 2>/dev/null || true)"
  if [ -n "$PAYLOAD" ]; then
    curl -sS -X POST "$FEISHU_WEBHOOK" \
      -H "Content-Type: application/json; charset=utf-8" \
      -d "$PAYLOAD" >> "$LOG" 2>&1 || true
  fi
fi

{
  echo "[INFO] 扫描结束: $(date '+%Y-%m-%d %H:%M:%S')  退出码: ${EXIT_CODE}"
} >> "$LOG"

exit "$EXIT_CODE"
