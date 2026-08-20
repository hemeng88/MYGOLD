# MYGOLD · 浙商积存金曲线档案

每天采集并保存 [浙商积存金](https://m.jdjygold.com/finance-gold/gold-standard/home/?productSku=1961543816) 的价格曲线，方便之后回看任意一天的走势。

对应仓库：[hemeng88/MYGOLD](https://github.com/hemeng88/MYGOLD)

## 它做什么

- 每分钟从京东金融接口拉取浙商积存金最新价，写入 SQLite
- 每 5 分钟同步当天完整走势点，固化成「当日曲线」
- Web 页面查看今日价格、历史曲线，并支持两日叠加对比
- 跨天后，昨天的曲线仍留在本地数据库里

第三方当日走势接口只保留「今天」的点。**后端需要保持运行**，历史才能越积越完整。

## 本地启动

需要 Python 3.9+ 和 Node 18+。

```bash
cd "/Users/dp/Desktop/for my love"
chmod +x start.sh
./start.sh
```

- 前端：http://127.0.0.1:5173
- 接口：http://127.0.0.1:8000/api/health
- 数据库：`backend/data/mygold.db`

也可以分开启动：

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
uvicorn app.main:app --app-dir backend --reload --port 8000

cd frontend
npm install
npm run dev
```

## 主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/quote/latest` | 最近一次采集到的报价 |
| GET | `/api/curve?date=YYYY-MM-DD` | 某日完整曲线 |
| GET | `/api/days` | 已归档交易日列表 |
| POST | `/api/collect` | 立刻采集一次 |
| GET | `/api/events?date=` | 带类型标签的异动事件 |
| GET | `/api/advice` | 当前该买还是该卖的参考价位 |
| GET | `/api/analysis/weights?window_days=` | 事件类型权重、波动区间、波动最大的交易日 |
| POST | `/api/analysis/refresh?window_days=` | 回填历史日线与快讯归档 |

## 数据从哪来

1. 主源：京东金融浙商积存金最新价 `stdLatestPrice`，产品 SKU `1961543816`
2. 当日曲线：GoldMonitor 的 `action=chart&type=zs`，用于补齐更密的盘中点
3. 长历史：新浪财经沪金连续 `AU0` 日线，积存金接口只给当天，做半年归因得靠它当代理标的
4. 快讯：华尔街见闻 7x24，黄金频道抓定期数据，全球频道只在波动日窗口内抓突发

采集结果落在五张表：`price_ticks`（逐笔报价）、`curve_points`（曲线点）、`daily_summaries`（开高低收）、
`daily_bars`（代理标的历史日线）、`news_flashes`（带标签的快讯归档）。

## 事件权重是怎么算的

1. 从日线里挑出 |日涨跌| ≥ 0.4% 的显著波动日
2. 把快讯按 18:00 切分归到交易日：收盘后的消息算下一个交易日
3. 用 `classify_macro_tags` 打标签，只留美联储、通胀、就业、石油、央行、汇率、利率、地缘这几类，
   每天固定出现的栏目、公司财报、无关小国数据都会被挡掉
4. 比较各类型当天的声量占比与它在所有波动日的平均占比，只有异常放量的才算当天主因，
   最多取两个，再把当天振幅均摊过去

得到的是相关归因，不是因果。中东这类话题在冲突期几乎天天有，所以必须比「异常程度」而不是「有没有出现」，
否则它会把别的类型全淹掉。每天 16:20 定时刷新一次。

## 买卖参考价位是怎么来的

行情页的「算一下该买还是该卖」调 `/api/advice`，规则都写在 `backend/app/analysis/advice.py`：

**价位**：沪金日线算 MA20、MA60、ATR14 和近 20 日高低点，再按基差换算到积存金报价上
（直接拿沪金价位会差几块钱，基差取两边收盘价比例的中位数）。买入档按 -0.5 ATR、-1.2 ATR、
MA20、近期低点排成阶梯，相差不到 0.5% 的合并掉。卖出档以保本价为硬下限——卖出费 0.4%，
低于保本价卖出必亏，所以有持仓且还没回本时，低于保本线的价位不会出现在卖出档里。

**方向**：位置和事件方向各占一半，两者都用实测胜率而不是拍出来的系数
（`backend/app/analysis/regime.py`）：

1. 位置分区：偏离 MA20 在 -1 个 ATR 以下 / 均线附近 / +1.5 个 ATR 以上
2. 事件方向：给快讯标题打「升级 / 缓和」，按声量加权算出最近两个交易日的净升级分
3. 每个分区的分数 = (历史次日上涨率 - 50%) / 50%，再按样本量收缩 n/(n+20)，样本薄的自动降权
4. 两个分数取平均，≥ +0.10 偏向买入，≤ -0.10 别加仓，中间观望

为什么用「升级 / 缓和」而不是「美联储 / 通胀 / 地缘」这些类型：实测下来事件**类型**对次日方向
没有可用信号（t 值全在 ±1.3 以内），但新闻的**方向性**有——剔掉「跌了就反弹」这个效应后偏相关
仍有 0.17。类型决定波动多大，方向性才决定往哪走。

样本外检验（前半段拟合、后半段验证，`backend/scripts/backtest_advice.py`）：说买入的 13 天
次日 +0.41%、62% 上涨，观望的 30 天 -0.08%、37%，基准是 +0.06%、45%。只有约 100 个可用交易日，
证据很薄，界面上每个因子都会显示样本天数和胜率。

这是按规则算出的参考位，不是投资建议。

## 部署到云服务器

容器会 `restart: unless-stopped`，服务器重启后自动起来，并持续采集：每分钟记价、每 5 分钟同步当日曲线。只要机器不关，历史就会按天攒下来。

### 本机一键推到服务器

把 `user@服务器IP` 换成你的 SSH 登录信息：

```bash
cd "/Users/dp/Desktop/for my love"
chmod +x deploy.sh scripts/publish-to-server.sh
./scripts/publish-to-server.sh root@你的服务器IP /opt/mygold
```

### 或者在服务器上自己部署

服务器需要已安装 Docker（含 Compose 插件）。

```bash
# Ubuntu / Debian
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"

git clone https://github.com/hemeng88/MYGOLD.git /opt/mygold
cd /opt/mygold
chmod +x deploy.sh
./deploy.sh
```

任意手机或电脑访问：`http://服务器公网IP`（默认 80 端口）。

首次上线（或新增归因功能后）要回填一次历史日线与快讯，约六分钟，之后每天 16:20 自动增量：

```bash
curl -X POST "http://服务器公网IP/api/analysis/refresh?window_days=180"
```

腾讯云轻量请在 **防火墙** 放行 TCP **80**。若 80 被系统自带网页占用，先停掉它，或改用 `MYGOLD_PORT=8000` 并放行 8000。

### 数据保存在哪

数据库挂在服务器项目目录的 `data/mygold.db`，容器删了数据还在。建议再加一条每日备份：

```bash
mkdir -p /opt/mygold/data/backup
crontab -e
# 每天 0:10 备份一份
10 0 * * * cp /opt/mygold/data/mygold.db /opt/mygold/data/backup/mygold-$(date +\%F).db
```

## 微信小程序

目录：`miniprogram/`。用[微信开发者工具](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html)导入该文件夹即可预览。

1. 开发者工具里关闭「校验合法域名、web-view、TLS」以便先连 `http://49.232.222.121`
2. 真机预览必须换成 **HTTPS 域名**，并在小程序后台配置 request 合法域名
3. 接口地址在 `miniprogram/app.js` 的 `apiBase`

小程序含三个页：行情曲线、手动持仓、超过手续费阈值的事件。

常用运维：

```bash
docker compose ps
docker compose logs -f --tail=100
docker compose restart
```
