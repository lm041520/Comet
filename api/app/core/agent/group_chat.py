"""群聊编排：多角色卡按「主持人」调度依次发言（接话式上下文）。

设计要点：
- 上下文用「文本 transcript」承载多方对话——每条消息带发言人前缀（【用户】/【角色名】），
  因为对某个角色而言，别人说的话既非自己（不能当 AIMessage）也非用户（不能当 HumanMessage），
  统一作为场景信息整段呈现最稳定。
- 每轮先调一次主持人 LLM 决定发言顺序（@ 指定时跳过主持人）。
- 角色依次发言，transcript 在一轮内动态累加，使后发言的角色能看到先发言角色刚说的话（接话）。
- 群聊不接工具、不做记忆萃取，纯人设对话。
"""
from collections.abc import AsyncGenerator

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.agent.prompt_renderer import render_agent_prompt
from app.core.logging import get_logger
from app.core.memory.json_utils import parse_json_object

logger = get_logger(__name__)

# transcript 截断：最近多少条消息参与上下文（越短首字越快、越省 token）
MAX_TRANSCRIPT_MESSAGES = 18
# 单个角色人设简介（喂主持人用）截断长度
BRIEF_MAX_CHARS = 80
# 主持人最多看的近期消息条数
HOST_RECENT_MESSAGES = 8


def build_transcript(history: list[dict], limit: int = MAX_TRANSCRIPT_MESSAGES) -> str:
    """把多方历史消息渲染成带发言人前缀的文本 transcript。

    history 元素：{role, content, sender_name}（user 消息 sender_name 为「用户」）。
    """
    rows = history[-limit:] if limit else history
    lines: list[str] = []
    for m in rows:
        content = (m.get("content") or "").strip()
        if not content:
            continue
        speaker = m.get("sender_name") or ("用户" if m.get("role") == "user" else "助手")
        lines.append(f"【{speaker}】{content}")
    return "\n".join(lines)


def _persona_brief(system_prompt: str) -> str:
    """从角色人设提取简介（喂主持人判断用），截断避免过长。"""
    text = (system_prompt or "").strip().replace("\n", " ")
    if len(text) > BRIEF_MAX_CHARS:
        text = text[:BRIEF_MAX_CHARS] + "…"
    return text or "（无特别设定）"


async def decide_speakers(
    host_model: ChatOpenAI,
    members: list[dict],
    transcript: str,
    user_text: str,
) -> list[str]:
    """主持人 LLM 决定本轮发言顺序，返回角色名列表。

    - 返回非空列表：这些角色按序发言。
    - 返回空列表：本轮 AI 不接话（如真人之间在互相聊天，无需 AI 插嘴）。
    - 解析失败/异常：兜底返回全体成员，保证对话不中断。
    members 元素：{id, name, system_prompt}。
    """
    member_names = [m["name"] for m in members]
    try:
        brief_members = [
            {"name": m["name"], "brief": _persona_brief(m.get("system_prompt", ""))}
            for m in members
        ]
        # 只给主持人看最近若干条，判断「该谁接话」足够
        recent = "\n".join(transcript.split("\n")[-HOST_RECENT_MESSAGES:])
        prompt = render_agent_prompt(
            "group_host.jinja2",
            members=brief_members,
            transcript=recent or "（暂无历史）",
            user_text=user_text,
        )
        resp = await host_model.ainvoke([HumanMessage(content=prompt)])
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        data = parse_json_object(content)
        speakers = data.get("speakers")
        # 字段缺失（解析失败）→ 兜底全员，保证对话不中断
        if speakers is None:
            return member_names
        # 过滤非法名字、去重保序；显式空列表表示「本轮 AI 不接话」，直接返回空
        valid: list[str] = []
        seen: set[str] = set()
        for name in speakers:
            if name in member_names and name not in seen:
                valid.append(name)
                seen.add(name)
        return valid
    except Exception as e:
        logger.warning("群聊主持人调度失败，回退全员发言: %s", e)
    return member_names


def build_speaker_messages(
    persona_prompt: str,
    self_name: str,
    member_names: list[str],
    transcript: str,
    with_tool_hint: bool = False,
    human_mode: bool = False,
) -> list:
    """构造某角色发言的 LLM 消息：人设 + 群聊场景说明 + 当前 transcript。

    with_tool_hint：群聊开了工具时传 True，附带"时效问题应联网"的引导。
    human_mode：该角色开了真人模式时叠加「真人聊天风格」段（口语短句、可多气泡）。
    """
    system = render_agent_prompt(
        "group_speaker.jinja2",
        persona_prompt=(persona_prompt or "").strip(),
        self_name=self_name,
        member_names="、".join(member_names),
        transcript=transcript or "（暂无历史）",
        human_mode=human_mode,
    )
    # 注入当前日期，让角色知道"今天"是哪天（开工具时对时效问题才会联网）
    from app.core.agent.context_hint import current_context_block

    system = system + "\n\n" + current_context_block(with_tool_hint=with_tool_hint)
    if human_mode:
        system = system + "\n\n" + render_agent_prompt("human_style.jinja2")
    return [SystemMessage(content=system)]


async def stream_speaker(
    model: ChatOpenAI,
    persona_prompt: str,
    self_name: str,
    member_names: list[str],
    transcript: str,
    human_mode: bool = False,
) -> AsyncGenerator[str, None]:
    """流式产出某角色的发言 token。"""
    messages = build_speaker_messages(
        persona_prompt, self_name, member_names, transcript, human_mode=human_mode
    )
    # 追加一条 user 轮次提示：部分 provider（智谱/通义等）不接受「只有 system、无 user」
    # 的消息数组（报 messages 参数非法），故显式补一条用户消息触发本角色发言。
    messages = [
        *messages,
        HumanMessage(
            content=f"现在轮到你「{self_name}」发言，请基于上面的群聊记录自然接话。"
        ),
    ]
    async for chunk in model.astream(messages):
        if chunk.content:
            text = (
                chunk.content
                if isinstance(chunk.content, str)
                else str(chunk.content)
            )
            yield text


def parse_mention(user_text: str, member_names: list[str]) -> str | None:
    """解析用户消息里的 @某角色，命中则返回角色名（跳过主持人，只让他回）。"""
    text = user_text or ""
    if "@" not in text:
        return None
    for name in member_names:
        if f"@{name}" in text:
            return name
    return None


__all__ = [
    "MAX_TRANSCRIPT_MESSAGES",
    "build_transcript",
    "decide_speakers",
    "stream_speaker",
    "parse_mention",
]
