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

DOMAIN=""
if [ -f .env ]; then
  DOMAIN="$(grep -E '^MYGOLD_DOMAIN=' .env | tail -n 1 | cut -d= -f2- | tr -d '[:space:]')"
fi
if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "ohmygod.icu" ]; then
  DOMAIN="ohmygold.icu"
fi
if [ -f .env ]; then
  grep -vE '^MYGOLD_DOMAIN=' .env > .env.tmp || true
  mv .env.tmp .env
fi
echo "MYGOLD_DOMAIN=$DOMAIN" >> .env

if [ -n "$DOMAIN" ]; then
  cat > Caddyfile <<EOF
http:// {
	reverse_proxy mygold:8000
}

$DOMAIN {
	reverse_proxy mygold:8000
}
EOF
  echo "已按域名 $DOMAIN 配置 HTTPS。"
else
  cat > Caddyfile <<EOF
:80 {
	reverse_proxy mygold:8000
}
EOF
  echo "未填写 MYGOLD_DOMAIN，只提供 http，没有小锁。"
fi

if [ ! -f /etc/docker/daemon.json ]; then
  echo "正在配置国内 Docker 镜像加速…"
  sudo mkdir -p /etc/docker
  sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "registry-mirrors": [
    "https://mirror.ccs.tencentyun.com",
    "https://docker.m.daocloud.io"
  ]
}
EOF
  sudo systemctl restart docker
fi

docker compose up -d --build --force-recreate
echo
if [ -n "$DOMAIN" ]; then
  echo "部署完成。用浏览器打开：https://$DOMAIN"
  echo "健康检查：https://$DOMAIN/api/health"
  echo "腾讯云防火墙请放行 TCP 80 和 443。"
else
  echo "部署完成。任意手机/电脑浏览器访问：http://服务器公网IP"
  echo "健康检查：http://服务器公网IP/api/health"
  echo "想要 https 小锁：在 /opt/mygold/.env 写上 MYGOLD_DOMAIN=你的域名 后再执行 sudo ./update.sh"
fi
echo "容器会开机自启，并持续按分钟采集、按天归档曲线。"
