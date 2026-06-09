"""图片多模态理解：生成详细描述 + OCR 文字 + 物体 + 场景。"""
import base64
import json

from app.core.llm.client import LLMClient
from app.core.logging import get_logger

logger = get_logger(__name__)

_EXT_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}

_PROMPT = """请仔细观察这张图片，用中文输出 JSON，包含以下字段：
- description: 对图片内容的详细描述（一段话，尽量具体，便于后续检索）
- ocr_text: 图片中出现的所有文字（没有则空字符串）
- objects: 图片中的主要物体列表（字符串数组）
- scene: 图片的场景类别（如：办公室、户外、文档截图、人物 等，一个词）

只输出 JSON，不要任何额外说明。"""


def guess_mime(file_ext: str) -> str:
    return _EXT_MIME.get(file_ext.lower(), "image/jpeg")


async def describe_image(
    client: LLMClient, content: bytes, file_ext: str
) -> dict:
    """调多模态模型理解图片，返回 {description, ocr_text, objects, scene}。

    大图先压缩（缩放 + 重编码），避免 base64 过大触发多模态接口 400/超限。
    """
    from app.core.rag.image_compress import compress_for_vision

    data, mime = compress_for_vision(content, file_ext)
    image_b64 = base64.b64encode(data).decode()
    answer = await client.vision(_PROMPT, image_b64, mime=mime, max_tokens=1024)
    return _parse(answer)


def _parse(answer: str) -> dict:
    text = answer.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    default = {"description": "", "ocr_text": "", "objects": [], "scene": ""}
    if start == -1 or end == -1:
        # 模型没按 JSON 返回，整段当描述
        default["description"] = answer.strip()[:2000]
        return default
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        default["description"] = answer.strip()[:2000]
        return default
    return {
        "description": str(data.get("description", ""))[:2000],
        "ocr_text": str(data.get("ocr_text", ""))[:2000],
        "objects": data.get("objects", []) if isinstance(data.get("objects"), list) else [],
        "scene": str(data.get("scene", ""))[:64],
    }
