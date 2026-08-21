#!/usr/bin/env bash
# 在服务器 /opt/mygold 执行：sudo ./update.sh
# 国内走 ghfast，拉最新 main 后重新构建容器。数据库在 data/ 里，不会被清掉。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

REMOTE="${UPDATE_REMOTE:-https://ghfast.top/https://github.com/hemeng88/MYGOLD.git}"
BRANCH="${UPDATE_BRANCH:-main}"

if [ ! -d .git ]; then
  echo "当前目录不是 git 仓库：$ROOT"
  exit 1
fi

echo "拉取 $BRANCH …"
git pull "$REMOTE" "$BRANCH"

chmod +x deploy.sh update.sh
./deploy.sh
