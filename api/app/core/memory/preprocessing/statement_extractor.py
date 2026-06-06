"""原子陈述抽取：把一段文本切成带类型/时间属性的原子陈述句。

调用对话模型，按受控的陈述类型（FACT/OPINION/PREDICTION/SUGGESTION）和
时间类型（STATIC/DYNAMIC/ATEMPORAL）标注，并标记指代是否未解析。
失败返回空列表，不中断流水线。
"""
from app.core.llm.client import LLMClient
from app.core.logging import get_logger
from app.core.memory.extraction.models import (
    ExtractedStatement,
    StatementExtractionResult,
)
from app.core.memory.json_utils import parse_json_object
from app.core.memory.prompt_renderer import render_prompt

logger = get_logger(__name__)


async def extract_statements(
    client: LLMClient, content: str, context: str | None = None
) -> list[ExtractedStatement]:
    """从一段文本抽取原子陈述句。"""
    prompt = render_prompt("extract_statement.jinja2", content=content, context=context)
    try:
        answer = await client.chat(
            [{"role": "user", "content": prompt}], temperature=0.2, max_tokens=2048
        )
        data = parse_json_object(answer)
        result = StatementExtractionResult.model_validate(data)
        return [s for s in result.statements if s.statement and s.statement.strip()]
    except Exception as e:
        logger.warning("陈述抽取失败（忽略该块）: %r", e)
        return []


__all__ = ["extract_statements"]
