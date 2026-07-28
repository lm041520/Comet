"""图片 Block 的低成本价值筛选规则。"""

from dataclasses import dataclass
from typing import Any

from app.core.rag.ingestion.models import BlockType, DocumentBlock

_HIGH_VALUE_KEYWORDS_BY_CATEGORY = {
    "architecture": {
        "架构图",
        "系统架构",
        "整体框架",
        "总体框架",
        "architecture",
        "framework",
        "system overview",
        "overall method",
    },
    "flowchart": {
        "流程图",
        "工作流",
        "处理流程",
        "flowchart",
        "pipeline",
        "workflow",
        "process diagram",
    },
    "chart": {
        "统计图",
        "柱状图",
        "折线图",
        "饼图",
        "收敛曲线",
        "趋势图",
        "chart",
        "plot",
        "curve",
        "convergence",
        "trend",
    },
    "diagram": {
        "示意图",
        "结构图",
        "机制图",
        "diagram",
        "schematic",
        "graph representation",
        "mechanism",
    },
}
_LOW_VALUE_KEYWORDS = {
    "logo",
    "图标",
    "头像",
    "水印",
    "二维码",
    "装饰",
    "icon",
    "avatar",
    "watermark",
    "qrcode",
}
_HIGH_VALUE_CATEGORIES = {"chart", "diagram", "flowchart", "architecture", "plot"}


@dataclass(frozen=True, slots=True)
class ImageValueDecision:
    should_enrich: bool
    category: str
    reason: str


def _image_dimensions(metadata: dict[str, Any]) -> tuple[float, float]:
    """优先读取像素尺寸；缺失时从 Docling bbox 推导版面尺寸。"""
    width = float(metadata.get("width", 0) or 0)
    height = float(metadata.get("height", 0) or 0)
    if width > 0 and height > 0:
        return width, height

    bbox = metadata.get("bbox")
    if not isinstance(bbox, dict):
        return 0, 0
    try:
        width = abs(float(bbox["r"]) - float(bbox["l"]))
        height = abs(float(bbox["t"]) - float(bbox["b"]))
    except (KeyError, TypeError, ValueError):
        return 0, 0
    return width, height


def _infer_high_value_category(searchable_text: str) -> str | None:
    for category, keywords in _HIGH_VALUE_KEYWORDS_BY_CATEGORY.items():
        if any(keyword in searchable_text for keyword in keywords):
            return category
    return None


def evaluate_image_value(
    block: DocumentBlock,
    *,
    repeated: bool = False,
) -> ImageValueDecision:
    """只允许有明确检索价值信号的图片进入 OCR/VLM 增强。"""
    if block.block_type != BlockType.IMAGE:
        return ImageValueDecision(False, "not_image", "不是图片 Block")
    if repeated:
        return ImageValueDecision(False, "repeated", "跨页重复图片")

    width, height = _image_dimensions(block.metadata)
    if width and height and (width < 96 or height < 96):
        return ImageValueDecision(False, "small", "图片尺寸过小")

    category = str(block.metadata.get("image_category", "")).lower()
    searchable_text = f"{block.content} {block.metadata.get('caption', '')}".lower()
    if category in _HIGH_VALUE_CATEGORIES:
        return ImageValueDecision(True, category, "解析器识别为高价值图形")
    if any(keyword in searchable_text for keyword in _LOW_VALUE_KEYWORDS):
        return ImageValueDecision(False, "decorative", "命中装饰性图片规则")
    inferred_category = _infer_high_value_category(searchable_text)
    if inferred_category:
        return ImageValueDecision(
            True,
            inferred_category,
            "标题或说明命中高价值图形规则",
        )
    return ImageValueDecision(False, "unknown", "缺少足够的检索价值证据")
