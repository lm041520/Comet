"""结构化 RAG 的离线检索指标。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrievalExpectation:
    query: str
    expected_source_id: str
    expected_page: int | None = None


def evaluate_retrieval_cases(
    cases: list[RetrievalExpectation],
    results_by_query: dict[str, list[dict]],
    *,
    top_k: int,
) -> dict[str, float | int]:
    """计算 Hit@K 与正确页码率，供固定样本集使用。"""
    if not cases:
        return {
            "case_count": 0,
            "hit_at_k": 0.0,
            "page_accuracy": 0.0,
        }
    hits = 0
    page_hits = 0
    page_cases = 0
    for case in cases:
        results = results_by_query.get(case.query, [])[:top_k]
        matched = next(
            (item for item in results if item.get("source_id") == case.expected_source_id),
            None,
        )
        if matched is not None:
            hits += 1
        if case.expected_page is not None:
            page_cases += 1
            if matched is not None:
                start = matched.get("page_start")
                end = matched.get("page_end") or start
                if start is not None and start <= case.expected_page <= end:
                    page_hits += 1
    return {
        "case_count": len(cases),
        "hit_at_k": round(hits / len(cases), 4),
        "page_accuracy": round(page_hits / page_cases, 4) if page_cases else 0.0,
    }
