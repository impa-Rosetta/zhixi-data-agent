"""Deterministic, non-data conversational responses for short social messages."""

from __future__ import annotations

import re
from typing import Literal

SmallTalkKind = Literal["greeting", "presence", "thanks", "farewell"]

_TRIM = re.compile(r"^[\s\W_]+|[\s\W_]+$", re.UNICODE)
_MESSAGES: dict[SmallTalkKind, frozenset[str]] = {
    "greeting": frozenset(
        {
            "你好",
            "您好",
            "你好呀",
            "您好呀",
            "早上好",
            "上午好",
            "下午好",
            "晚上好",
            "hello",
            "hi",
        }
    ),
    "presence": frozenset({"在吗", "在不在", "有人吗"}),
    "thanks": frozenset({"谢谢", "感谢", "多谢", "辛苦了", "谢谢你"}),
    "farewell": frozenset({"再见", "拜拜", "回头见", "下次见"}),
}


def classify_small_talk(message: str) -> SmallTalkKind | None:
    """Recognize only short, unambiguous social messages to avoid swallowing real requests."""
    normalized = _TRIM.sub("", message.casefold())
    for kind, messages in _MESSAGES.items():
        if normalized in messages:
            return kind
    return None


def small_talk_response(message: str) -> dict[str, object]:
    kind = classify_small_talk(message)
    responses = {
        "greeting": (
            "你好！我是智析 Agent，很高兴见到你。"
            "我可以帮你查看已授权的数据目录、分析制造质量指标，也可以在结果出来后继续追问。"
            "你今天想看什么？"
        ),
        "presence": "在的。你可以直接告诉我想查看的数据、指标或分析问题，我会接着处理。",
        "thanks": "不客气！如果还想继续拆分、比较或解释刚才的结果，直接接着问就可以。",
        "farewell": "好的，再见！这段会话会保留，回来后可以继续刚才的分析。",
    }
    selected = kind or "greeting"
    return {
        "message": responses[selected],
        "kind": selected,
        "trust": "system",
    }


__all__ = ["SmallTalkKind", "classify_small_talk", "small_talk_response"]
