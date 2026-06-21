"""清理评测数据：删除 EVAL_USER_ID 在 ES（chunk）与 Neo4j（图谱）的全部数据。

只删评测命名空间，不碰真实用户。run_extraction 只写 Neo4j（不写 PG memories），故无需清 PG。
"""
from app.core.rag.es_index import CHUNKS_INDEX
from app.db.elastic import get_es
from app.repositories.neo4j.memory_graph_repository import MemoryGraphRepository
from eval.eval_config import EVAL_USER_ID


async def teardown() -> None:
    uid = str(EVAL_USER_ID)
    # ES：删该用户所有 chunk
    es = get_es()
    try:
        await es.delete_by_query(
            index=CHUNKS_INDEX,
            body={"query": {"term": {"user_id": uid}}},
            refresh=True,
            conflicts="proceed",
        )
    except Exception as e:  # noqa: BLE001
        print(f"[teardown] 清 ES 失败（忽略）: {e}")
    # Neo4j：删该用户全部图数据
    try:
        await MemoryGraphRepository().delete_user_graph(uid)
    except Exception as e:  # noqa: BLE001
        print(f"[teardown] 清 Neo4j 失败（忽略）: {e}")
