"""图片业务服务：上传/列表/详情/删除/检索。"""
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.logging import get_logger
from app.core.rag.indexing.es_store import delete_by_source
from app.core.rag.retrieval import hybrid_search
from app.core.storage import build_file_key, get_storage
from app.models.image_model import IMG_STATUS_PENDING, Image
from app.repositories.image_repository import ImageRepository
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.tag_repository import TagRepository

logger = get_logger(__name__)

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB


class ImageService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ImageRepository(session)
        self.tag_repo = TagRepository(session)
        self.kb_repo = KnowledgeBaseRepository(session)

    async def _dispatch(self, image_id: uuid.UUID) -> None:
        from app.tasks.image import process_image_task

        process_image_task.delay(str(image_id))

    async def _resolve_kb_id(
        self, user_id: uuid.UUID, kb_id: uuid.UUID | None
    ) -> uuid.UUID:
        """确定图片归属库：指定了就校验归属，没指定落默认库。"""
        if kb_id:
            kb = await self.kb_repo.get(user_id, kb_id)
            if not kb:
                raise BizError("知识库不存在", code=3040, status_code=404)
            return kb.id
        return (await self.kb_repo.ensure_default(user_id)).id

    async def upload(
        self,
        user_id: uuid.UUID,
        file_name: str,
        content: bytes,
        kb_id: uuid.UUID | None = None,
    ) -> Image:
        ext = Path(file_name).suffix.lower()
        if ext not in SUPPORTED_IMAGE_EXTS:
            raise BizError(f"不支持的图片类型: {ext}", code=3020)
        if len(content) > MAX_IMAGE_SIZE:
            raise BizError("图片超过 20MB 限制", code=3021)

        resolved_kb = await self._resolve_kb_id(user_id, kb_id)
        img_id = uuid.uuid4()
        file_key = build_file_key(str(user_id), "images", str(img_id), ext)
        await get_storage().save(file_key, content)

        img = Image(
            id=img_id,
            user_id=user_id,
            kb_id=resolved_kb,
            file_name=file_name,
            file_ext=ext,
            file_size=len(content),
            file_key=file_key,
            status=IMG_STATUS_PENDING,
        )
        await self.repo.create(img)
        await self._dispatch(img_id)
        logger.info("图片上传: user=%s id=%s name=%s", user_id, img_id, file_name)
        return img

    async def ingest_from_chat(
        self, user_id: uuid.UUID, file_key: str
    ) -> Image | None:
        """把对话里上传的图片纳入图片库：复用已上传的文件，建 Image 记录并派发处理。

        按 file_key 去重，已入库则跳过。文件名用「对话图片_日期」。
        作为对话的副作用调用，失败不应影响主流程。
        """
        existing = await self.repo.get_by_file_key(user_id, file_key)
        if existing:
            return existing
        ext = Path(file_key).suffix.lower() or ".jpg"
        from datetime import datetime

        resolved_kb = (await self.kb_repo.ensure_default(user_id)).id
        file_name = f"对话图片_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        img = Image(
            id=uuid.uuid4(),
            user_id=user_id,
            kb_id=resolved_kb,
            file_name=file_name,
            file_ext=ext,
            file_size=0,  # 对话图复用已存文件，体积非关键信息
            file_key=file_key,
            status=IMG_STATUS_PENDING,
        )
        await self.repo.create(img)
        await self._dispatch(img.id)
        logger.info("对话图片入库: user=%s id=%s key=%s", user_id, img.id, file_key)
        return img

    async def _get_or_404(self, user_id: uuid.UUID, image_id: uuid.UUID) -> Image:
        img = await self.repo.get(user_id, image_id)
        if not img:
            raise BizError("图片不存在", code=3022, status_code=404)
        return img

    async def list_images(
        self,
        user_id: uuid.UUID,
        page: int,
        page_size: int,
        tag: str | None = None,
        kb_id: uuid.UUID | None = None,
    ) -> tuple[list[Image], int]:
        return await self.repo.list_paged(user_id, page, page_size, tag, kb_id)

    async def get_detail(self, user_id: uuid.UUID, image_id: uuid.UUID) -> Image:
        return await self._get_or_404(user_id, image_id)

    async def search(
        self, user_id: uuid.UUID, query: str, top_k: int
    ) -> list[dict]:
        """图片语义检索：ES 召回阶段即限定 source_type=image。"""
        return await hybrid_search(
            self.session, user_id, query, top_k=top_k, source_type="image"
        )

    async def delete(self, user_id: uuid.UUID, image_id: uuid.UUID) -> None:
        img = await self._get_or_404(user_id, image_id)
        await delete_by_source(str(user_id), str(image_id))
        try:
            await get_storage().delete(img.file_key)
        except Exception as e:
            logger.warning("删除图片文件失败（忽略）: %s", e)
        await self.repo.delete(img)
        logger.info("删除图片: user=%s id=%s", user_id, image_id)

    async def move_to_kb(
        self, user_id: uuid.UUID, image_id: uuid.UUID, kb_id: uuid.UUID
    ) -> Image:
        """把图片移动到另一个知识库，并同步回写 ES chunk 的 kb_id。"""
        from app.core.rag.indexing.es_store import update_kb_by_source

        img = await self._get_or_404(user_id, image_id)
        kb = await self.kb_repo.get(user_id, kb_id)
        if not kb:
            raise BizError("知识库不存在", code=3040, status_code=404)
        img.kb_id = kb.id
        await self.repo.save(img)
        try:
            await update_kb_by_source(str(user_id), str(image_id), str(kb.id))
        except Exception as e:
            logger.warning("移动图片回写 ES kb_id 失败（忽略）: %s", e)
        return img

    async def to_out_dict(self, img: Image) -> dict:
        tags = await self.tag_repo.get_image_tags(img.id)
        return {
            "id": str(img.id),
            "kb_id": str(img.kb_id) if img.kb_id else None,
            "file_name": img.file_name,
            "file_ext": img.file_ext,
            "file_size": img.file_size,
            "url": get_storage().get_url(img.file_key),
            "description": img.description,
            "objects": img.objects,
            "scene": img.scene,
            "tags": tags,
            "status": img.status,
            "error_msg": img.error_msg,
            "created_at": img.created_at.isoformat(),
        }
