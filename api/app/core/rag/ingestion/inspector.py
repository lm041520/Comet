"""文件体检：以低成本信号描述文件，不负责选择或执行解析器。"""

from app.core.exceptions import BizError
from app.core.rag.ingestion.models import DocumentProfile


def normalize_file_ext(file_ext: str) -> str:
    ext = file_ext.strip().lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    return ext


class FileInspector:
    """生成解析器路由所需的基础文件特征。"""

    def inspect(self, file_ext: str, content: bytes) -> DocumentProfile:
        ext = normalize_file_ext(file_ext)
        if not content:
            return DocumentProfile(file_ext=ext, file_size=0)
        if ext != ".pdf":
            return DocumentProfile(file_ext=ext, file_size=len(content))

        try:
            import fitz

            page_count = 0
            text_chars = 0
            image_count = 0
            multicolumn_pages = 0
            with fitz.open(stream=content, filetype="pdf") as document:
                page_count = document.page_count
                for page in document:
                    text_chars += len(page.get_text().strip())
                    image_count += len(page.get_images(full=True))
                    if self._looks_multicolumn(page):
                        multicolumn_pages += 1
            density = text_chars / max(page_count, 1)
            # 短标题、票据编号等正常文本页也可能低于 40 字，不能只靠文本密度判扫描件。
            # 首版使用“无文本层”或“低文本密度 + 基本每页都有图片”的组合证据。
            scanned_pdf_risk = page_count > 0 and (
                text_chars == 0
                or (density < 40 and image_count >= page_count)
            )
            image_heavy = image_count >= 3 and image_count >= page_count
            advanced_parser_recommended = scanned_pdf_risk or multicolumn_pages > 0 or image_heavy
            return DocumentProfile(
                file_ext=ext,
                file_size=len(content),
                page_count=page_count,
                text_char_count=text_chars,
                image_count=image_count,
                text_density=density,
                scanned_pdf_risk=scanned_pdf_risk,
                features={
                    "multicolumn_pages": multicolumn_pages,
                    "image_heavy": image_heavy,
                    "advanced_parser_recommended": advanced_parser_recommended,
                },
            )
        except Exception as exc:
            raise BizError("PDF 文件体检失败，文件可能已损坏", code=3002) from exc

    @staticmethod
    def _looks_multicolumn(page) -> bool:
        page_width = float(page.rect.width or 1)
        narrow_blocks = []
        for block in page.get_text("blocks"):
            x0, _y0, x1, _y1, text = block[:5]
            if not str(text).strip():
                continue
            width = float(x1 - x0)
            if width < page_width * 0.65:
                narrow_blocks.append((float(x0 + x1) / 2, len(str(text))))
        left = sum(1 for center, chars in narrow_blocks if center < page_width / 2 and chars > 30)
        right = sum(1 for center, chars in narrow_blocks if center >= page_width / 2 and chars > 30)
        return left >= 2 and right >= 2
