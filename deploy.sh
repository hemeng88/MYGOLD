#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "未检测到 Docker。请先安装 Docker 后再执行本脚本。"
  echo "Ubuntu / Debian 可用："
  echo "  curl -fsSL https://get.docker.com | sudo sh"
  echo "  sudo usermod -aG docker \"\$USER\""
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "未检测到 docker compose，请安装 Docker Compose 插件后重试。"
  exit 1
fi

mkdir -p data
if [ -f backend/data/mygold.db ] && [ ! -f data/mygold.db ]; then
  cp backend/data/mygold.db data/mygold.db
  echo "已带上本地已采集的数据库。"
fi

if [ ! -f .env ]; then
  cp .env.example .env
fi

docker compose up -d --build
echo
echo "部署完成。浏览器访问：http://服务器IP:${MYGOLD_PORT:-8000}"
echo "健康检查：http://服务器IP:${MYGOLD_PORT:-8000}/api/health"
echo "容器会开机自启，并持续按分钟采集、按天归档曲线。"
