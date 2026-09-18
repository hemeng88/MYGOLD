"""通过 OpenClaw webhook 推送飞书消息。

MYGOLD 在定时任务的关键节点调 notify()，OpenClaw 收到 wake 事件后会转发到飞书。
发送失败只 logger.error，不抛——不影响主流程。
"""

from __future__ import annotations

import logging
from typing import List, Optional

import httpx

from .config import settings

logger = logging.getLogger("mygold.notify")

_LEVEL_PREFIX = {
    "info": "",
    "warn": "⚠️ ",
    "error": "❌ ",
}


async def notify(
    title: str,
    body: Optional[str] = None,
    level: str = "info",
) -> bool:
    """推一条消息到飞书（经 OpenClaw webhook）。

    Args:
        title: 消息标题，会作为飞书消息第一行。
        body: 可选正文，多行用 \\n。
        level: info / warn / error，会拼到 title 前缀里。

    Returns:
        True 表示 HTTP 2xx；False 表示失败或未配置。
    """
    url = settings.openclaw_webhook_url
    token = settings.openclaw_webhook_token
    if not url or not token:
        logger.debug("OpenClaw webhook 未配置（MYGOLD_OPENCLAW_WEBHOOK_URL/TOKEN 为空），跳过推送")
        return False

    prefix = _LEVEL_PREFIX.get(level, "")
    text = f"{prefix}{title}"
    if body:
        text += f"\n{body}"

    payload = {"text": text, "mode": "now"}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
    except httpx.HTTPError as exc:
        logger.error("OpenClaw webhook 调用失败：%s", exc)
        return False

    if resp.status_code >= 400:
        logger.error("OpenClaw webhook 返回 %s：%s", resp.status_code, resp.text[:200])
        return False
    return True


async def notify_lines(lines: List[str], title: str, level: str = "info") -> bool:
    """把多行内容拼成一个 body 推送，行为同 notify()。"""
    return await notify(title, body="\n".join(lines), level=level)