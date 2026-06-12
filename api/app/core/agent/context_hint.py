"""对话当前上下文提示：把"今天是哪天"直接写进 system prompt。

为什么需要：LLM 的知识有截止日期，它默认以为自己"知道今天"，于是面对
"今天股票怎么样""最近的新闻"这类问题时会凭训练数据里的旧信息作答，根本
意识不到信息已过时、需要联网或查时间工具。把当前真实日期注入 system prompt，
模型一开始就知道"现在"是何时，才会主动对时效性问题调用联网/时间工具。

这是业界通用做法（主流助手都在 system prompt 注入当前日期）。
"""
from datetime import datetime, timedelta, timezone

# 北京时间（东八区），显式固定，不依赖服务器本地时区
_CST = timezone(timedelta(hours=8))
_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def current_context_block(*, with_tool_hint: bool = True) -> str:
    """生成当前日期 + 时效性引导的提示块，追加进 system prompt。

    with_tool_hint：是否附带"时效问题用联网工具"的引导（有工具时才加）。
    """
    now = datetime.now(_CST)
    weekday = _WEEKDAYS[now.weekday()]
    lines = [
        f"【当前时间】今天是 {now.strftime('%Y年%m月%d日')}（{weekday}），"
        f"现在 {now.strftime('%H:%M')}（北京时间）。",
    ]
    if with_tool_hint:
        lines.append(
            "你的训练知识有截止日期，可能落后于现在。当问题涉及实时或时效性信息"
            "（如今天/最近的股价、行情、新闻、天气、赛事、热点等），不要凭记忆回答，"
            "应调用联网搜索工具获取最新信息；涉及具体日期/星期可调用时间工具。"
        )
    return "\n".join(lines)


__all__ = ["current_context_block"]
