"""首版解析质量判断：只给可解释状态和告警，不生成伪精确分数。"""

from app.core.rag.ingestion.models import ParsedDocument, ParseStatus


def apply_parse_quality(parsed: ParsedDocument) -> ParsedDocument:
    if not parsed.blocks:
        parsed.status = ParseStatus.FAILED
        if "解析结果为空" not in parsed.warnings:
            parsed.warnings.append("解析结果为空")
        return parsed
    if parsed.status == ParseStatus.FALLBACK:
        return parsed
    parsed.status = ParseStatus.WARNING if parsed.warnings else ParseStatus.OK
    return parsed
