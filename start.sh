#!/bin/bash
# ════════════════════════════════════════════════════════════
#  Railway.app 启动脚本
#  Railway 自动注入 PORT 环境变量
# ════════════════════════════════════════════════════════════

set -e

# Railway 平台变量
export PORT="${PORT:-5050}"
export HOST="${HOST:-0.0.0.0}"
export PYTHONUNBUFFERED=1

echo "╔══════════════════════════════════════════════╗"
echo "║   月白 AI Agent · Railway Edition            ║"
echo "║   2325102015 黄凯豪                          ║"
echo "╚══════════════════════════════════════════════╝"
echo "  🧠 LLM: ${DEEPSEEK_MODEL:-deepseek-chat}"
echo "  🚀 端口: $PORT"
echo "  🐍 Python: $(python --version 2>&1)"

# Gunicorn 启动 — 绑定 Railway 给的 PORT
exec gunicorn wsgi:app \
    --bind "0.0.0.0:$PORT" \
    --workers "${WORKERS:-2}" \
    --worker-class sync \
    --timeout 180 \
    --keep-alive 5 \
    --max-requests 500 \
    --max-requests-jitter 100 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    --preload
