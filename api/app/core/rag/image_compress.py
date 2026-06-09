"""图片压缩工具：把大图缩放 + 重编码到适合多模态接口的大小。

多模态接口对单图 base64 体积有限制，原图过大（手机拍摄常见 5~20MB）会触发 400。
压缩仅用于送模型，不影响原图存储。
"""
import io

from app.core.logging import get_logger

logger = get_logger(__name__)

# 送图上限：最长边像素 + 目标字节（base64 前）
_MAX_EDGE = 1568
_TARGET_BYTES = 3 * 1024 * 1024  # ~3MB，base64 后约 4MB，主流多模态接口可接受


def compress_for_vision(raw: bytes, file_ext: str) -> tuple[bytes, str]:
    """把图片压到适合多模态接口的大小：缩放最长边 + JPEG 重编码。

    返回 (字节, mime)。小图或压缩失败时返回原图。
    """
    ext = (file_ext or "").lower()
    is_png = ext in (".png", "png")
    mime = "image/png" if is_png else "image/jpeg"
    if len(raw) <= _TARGET_BYTES:
        return raw, mime
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        # 统一转 RGB 走 JPEG（带透明通道的贴白底），体积可控
        if img.mode in ("RGBA", "P", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
        w, h = img.size
        longest = max(w, h)
        if longest > _MAX_EDGE:
            scale = _MAX_EDGE / longest
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        data = raw
        for quality in (85, 70, 55, 40):
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            data = buf.getvalue()
            if len(data) <= _TARGET_BYTES:
                return data, "image/jpeg"
        return data, "image/jpeg"
    except Exception as e:
        logger.warning("图片压缩失败，用原图: %s", e)
        return raw, mime


__all__ = ["compress_for_vision"]
