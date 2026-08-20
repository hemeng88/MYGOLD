#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
fi
# shellcheck disable=SC1091
source backend/.venv/bin/activate
pip install -r backend/requirements.txt

if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm install)
fi

export PYTHONPATH="$ROOT/backend"
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload &
BACK_PID=$!
trap 'kill $BACK_PID 2>/dev/null || true' EXIT

cd frontend
npm run dev
