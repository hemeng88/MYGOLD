#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "" ]; then
  echo "用法: ./scripts/publish-to-server.sh user@服务器IP [远程目录]"
  echo "示例: ./scripts/publish-to-server.sh root@1.2.3.4 /opt/mygold"
  exit 1
fi

HOST="$1"
REMOTE_DIR="${2:-/opt/mygold}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

ssh "$HOST" "mkdir -p '$REMOTE_DIR'"
rsync -az --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'backend/.venv' \
  --exclude 'node_modules' \
  --exclude 'frontend/node_modules' \
  --exclude 'frontend/dist' \
  --exclude 'frontend/.vite' \
  --exclude '__pycache__' \
  --exclude '.DS_Store' \
  "$ROOT/" "$HOST:$REMOTE_DIR/"

ssh -t "$HOST" "cd '$REMOTE_DIR' && chmod +x deploy.sh && ./deploy.sh"
