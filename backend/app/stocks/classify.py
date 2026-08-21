"""把公告/标题打成公司动作标签和方向分。

这是关键词规则，不是训练过的模型；没有方向词就给 0，宁可不说话。
"""

from typing import List, Tuple

NOISE = ("收盘", "午评", "早评", "晚报", "早餐", "资金流向", "大宗交易", "吸金", "午报", "成交额")

BULL = (
    ("回购", 0.65),
    ("增持", 0.55),
    ("业绩预增", 0.5),
    ("预增", 0.45),
    ("超预期", 0.45),
    ("同比增长", 0.4),
    ("同比增", 0.4),
    ("高增", 0.4),
    ("中标", 0.4),
    ("收购", 0.4),
    ("并购", 0.4),
    ("入股", 0.35),
    ("入局", 0.3),
    ("斥资", 0.25),
    ("签约", 0.35),
    ("大订单", 0.4),
    ("获批", 0.35),
    ("批准", 0.3),
    ("涨价", 0.3),
    ("提价", 0.3),
    ("股权激励", 0.3),
    ("扩产", 0.25),
    ("投产", 0.25),
    ("分红", 0.2),
    ("派息", 0.2),
    ("扭亏", 0.35),
)
BEAR = (
    ("立案", -0.7),
    ("处罚", -0.55),
    ("调查", -0.5),
    ("减持", -0.55),
    ("业绩预减", -0.5),
    ("预减", -0.45),
    ("预亏", -0.5),
    ("增收不增利", -0.25),
    ("同比下降", -0.4),
    ("同比降", -0.4),
    ("亏损", -0.4),
    ("问询", -0.35),
    ("警示", -0.3),
    ("下调", -0.3),
    ("降级", -0.3),
    ("质押", -0.2),
    ("召回", -0.35),
    ("违约", -0.4),
)
MARKET_BULL = (
    ("降准", 0.45),
    ("降息", 0.45),
    ("活跃资本市场", 0.4),
    ("印花税", 0.25),
    ("北向净流入", 0.3),
    ("增量资金", 0.25),
)
MARKET_BEAR = (
    ("北向净流出", -0.3),
    ("收紧", -0.3),
    ("监管趋严", -0.35),
    ("风险警示", -0.25),
)
NEGATE = ("终止", "取消", "未实施", "未完成", "失败", "不及", "下滑", "下降", "减少")


def is_noise(title: str) -> bool:
    text = title or ""
    if any(word in text for word in NOISE):
        return True
    return "只" in text and ("上涨" in text or "下跌" in text)


def classify_title(title: str, market: bool = False) -> Tuple[List[str], float]:
    text = title or ""
    if is_noise(text):
        return [], 0.0
    pairs = (MARKET_BULL + MARKET_BEAR) if market else (BULL + BEAR)
    if market:
        pairs = pairs + BULL[:4] + BEAR[:4]
    hits: List[Tuple[str, float]] = []
    for word, score in pairs:
        if word in text:
            hits.append((word, score))
    if not hits:
        return [], 0.0
    if any(flag in text for flag in NEGATE):
        hits = [(word, -score * 0.7) for word, score in hits]
    tags = []
    for word, _score in hits:
        if word not in tags:
            tags.append(word)
    score = sum(item[1] for item in hits) / len(hits)
    if score > 1:
        score = 1.0
    if score < -1:
        score = -1.0
    return tags[:3], round(score, 3)
