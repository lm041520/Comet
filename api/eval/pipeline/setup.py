"""评测数据写入：把 fixtures 的语料灌进 ES、对话萃取进 Neo4j，全部写在 EVAL_USER_ID 名下。

这一步本身也在"测写入链路"——复用 app 真实的分块/向量化/萃取流程，与生产一致。
source_id 用语料文件名（去扩展名），便于 gold 的 relevant_doc_ids 直接按文件名引用。
"""
import json
from pathlib import Path

from app.core.memory.extraction.orchestrator import run_extraction
from app.core.memory.graph_schema import ensure_graph_schema
from app.core.rag.chunker import chunk_parent_child
from app.core.rag.es_index import CHUNK_TYPE_CHILD, CHUNK_TYPE_PARENT, ensure_index
from app.core.rag.es_store import build_chunk_doc, bulk_index, delete_by_source
from eval.eval_config import EVAL_USER_ID

_FIXTURES = Path(__file__).parent.parent / "fixtures"
_CORPUS_DIR = _FIXTURES / "corpus"
_DIALOGUES = _FIXTURES / "dialogues.json"


async def ingest_corpus(embed_client) -> int:
    """把 fixtures/corpus/*.md 分块+向量化+写 ES。返回写入文档数。"""
    await ensure_index()
    uid = str(EVAL_USER_ID)
    docs = sorted(_CORPUS_DIR.glob("*.md")) + sorted(_CORPUS_DIR.glob("*.txt"))
    total = len(docs)
    for i, path in enumerate(docs, 1):
        source_id = path.stem  # 文件名（去扩展名）作为 source_id，gold 按它引用
        print(f"  [语料] {i}/{total} {source_id} 分块+向量化+写 ES…")
        text = path.read_text(encoding="utf-8")
        parents = chunk_parent_child(text)
        await delete_by_source(uid, source_id)  # 幂等：先清旧
        es_docs: list[dict] = []
        for parent in parents:
            parent_doc = build_chunk_doc(
                user_id=uid, source_type="document", source_id=source_id,
                doc_name=path.name, chunk_type=CHUNK_TYPE_PARENT,
                content=parent.content, vector=None,
            )
            es_docs.append(parent_doc)
            if parent.children:
                vectors = await embed_client.embed(parent.children)
                for child, vec in zip(parent.children, vectors):
                    es_docs.append(build_chunk_doc(
                        user_id=uid, source_type="document", source_id=source_id,
                        doc_name=path.name, chunk_type=CHUNK_TYPE_CHILD,
                        content=child, vector=vec, parent_id=parent_doc["_id"],
                    ))
        await bulk_index(es_docs)
    return len(docs)


async def ingest_memory(chat_client, embed_client) -> int:
    """把 fixtures/dialogues.json 逐段萃取进 Neo4j。返回处理对话数。"""
    await ensure_graph_schema()
    dialogues = json.loads(_DIALOGUES.read_text(encoding="utf-8"))
    total = len(dialogues)
    for i, text in enumerate(dialogues, 1):
        print(f"  [记忆] {i}/{total} 萃取入图：{text[:24]}…")
        await run_extraction(
            chat_client=chat_client, embed_client=embed_client,
            user_id=str(EVAL_USER_ID), text=text, source="manual",
        )
    return len(dialogues)


async def setup_all(chat_client, embed_client) -> dict:
    """写入语料 + 记忆。返回统计。"""
    n_docs = await ingest_corpus(embed_client)
    n_dialogues = await ingest_memory(chat_client, embed_client)
    return {"docs": n_docs, "dialogues": n_dialogues}
