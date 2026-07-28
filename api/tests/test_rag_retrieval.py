"""混合检索过滤与 Trace 字段回归测试。"""

import asyncio
import uuid

from app.core.rag.retrieval import search as search_module


class FakeEmbeddingClient:
    async def embed_one(self, query: str) -> list[float]:
        assert query
        return [0.1, 0.2]


class FakeFailingRerankClient:
    async def rerank(self, *_args, **_kwargs):
        raise RuntimeError("rerank unavailable")


class FakeElasticsearch:
    def __init__(self):
        self.calls: list[dict] = []

    async def search(self, *, index: str, body: dict) -> dict:
        self.calls.append(body)
        if "knn" in body:
            return {
                "hits": {
                    "hits": [
                        {
                            "_id": "child-1",
                            "_score": 0.9,
                            "_source": {
                                "content": "命中的子块",
                                "chunk_type": "child",
                                "parent_id": "parent-1",
                                "source_id": "11111111-1111-1111-1111-111111111111",
                                "source_type": "document",
                                "doc_name": "测试.pdf",
                                "kb_id": "kb-1",
                                "block_ids": ["22222222-2222-2222-2222-222222222222"],
                                "block_types": ["paragraph"],
                                "page_start": 2,
                                "page_end": 2,
                                "heading_path": ["第二章"],
                                "chunk_index": 1,
                                "parser_name": "pymupdf",
                            },
                        }
                    ]
                }
            }
        if body.get("query", {}).get("bool", {}).get("must"):
            return {
                "hits": {
                    "hits": [
                        {
                            "_id": "child-1",
                            "_score": 5.0,
                            "_source": {
                                "content": "命中的子块",
                                "chunk_type": "child",
                                "parent_id": "parent-1",
                                "source_id": "11111111-1111-1111-1111-111111111111",
                                "source_type": "document",
                                "doc_name": "测试.pdf",
                                "kb_id": "kb-1",
                                "block_ids": ["22222222-2222-2222-2222-222222222222"],
                                "block_types": ["paragraph"],
                                "page_start": 2,
                                "page_end": 2,
                                "heading_path": ["第二章"],
                                "chunk_index": 1,
                                "parser_name": "pymupdf",
                            },
                        }
                    ]
                }
            }
        return {
            "hits": {
                "hits": [
                    {
                        "_id": "parent-1",
                        "_source": {"content": "完整的父块上下文"},
                    }
                ]
            }
        }


def test_hybrid_search_keeps_user_and_kb_filters(monkeypatch) -> None:
    fake_es = FakeElasticsearch()

    async def fake_get_client(*_args, **_kwargs):
        return FakeEmbeddingClient()

    async def fake_get_optional(*_args, **_kwargs):
        return None

    monkeypatch.setattr(search_module, "get_es", lambda: fake_es)
    monkeypatch.setattr(search_module, "get_client_for_type", fake_get_client)
    monkeypatch.setattr(
        search_module,
        "get_optional_client_for_type",
        fake_get_optional,
    )

    user_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
    results = asyncio.run(
        search_module.hybrid_search(
            None,
            user_id,
            "测试问题",
            top_k=3,
            source_type="document",
            kb_ids=["kb-1"],
        )
    )

    assert results[0]["content"] == "完整的父块上下文"
    assert results[0]["matched_content"] == "命中的子块"
    assert results[0]["page_start"] == 2
    assert results[0]["block_types"] == ["paragraph"]

    for call in fake_es.calls[:2]:
        filters = (
            call["knn"]["filter"]["bool"]["filter"]
            if "knn" in call
            else call["query"]["bool"]["filter"]
        )
        assert {"term": {"user_id": str(user_id)}} in filters
        assert {"terms": {"kb_id": ["kb-1"]}} in filters


def test_empty_kb_scope_returns_without_retrieval(monkeypatch) -> None:
    def fail_get_es():
        raise AssertionError("空知识库范围不应访问 ES")

    monkeypatch.setattr(search_module, "get_es", fail_get_es)

    results = asyncio.run(
        search_module.hybrid_search(
            None,
            uuid.uuid4(),
            "不会执行",
            kb_ids=[],
        )
    )

    assert results == []


def test_rerank_failure_returns_fusion_results(monkeypatch) -> None:
    fake_es = FakeElasticsearch()

    async def fake_get_client(*_args, **_kwargs):
        return FakeEmbeddingClient()

    async def fake_get_optional(*_args, **_kwargs):
        return FakeFailingRerankClient()

    monkeypatch.setattr(search_module, "get_es", lambda: fake_es)
    monkeypatch.setattr(search_module, "get_client_for_type", fake_get_client)
    monkeypatch.setattr(
        search_module,
        "get_optional_client_for_type",
        fake_get_optional,
    )

    trace = asyncio.run(
        search_module._run_hybrid_search(
            None,
            uuid.uuid4(),
            "测试降级",
            top_k=3,
            recall_size=10,
            kb_ids=["kb-1"],
        )
    )

    assert trace["rerank_used"] is False
    assert trace["rerank_error"] == "rerank unavailable"
    assert trace["results"][0]["child_content"] == "命中的子块"
