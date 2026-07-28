"""图片筛选、指定解析器和离线评测指标测试。"""

from app.core.rag.evaluation import RetrievalExpectation, evaluate_retrieval_cases
from app.core.rag.ingestion.enrichers import evaluate_image_value
from app.core.rag.ingestion.models import BlockType, DocumentBlock, DocumentProfile
from app.core.rag.ingestion.router import ParserRouter


def test_image_enrichment_only_accepts_high_value_picture():
    chart = DocumentBlock(
        content="系统架构图",
        block_type=BlockType.IMAGE,
        metadata={"width": 1200, "height": 800},
    )
    logo = DocumentBlock(
        content="公司 Logo",
        block_type=BlockType.IMAGE,
        metadata={"width": 600, "height": 300},
    )

    assert evaluate_image_value(chart).should_enrich is True
    assert evaluate_image_value(logo).should_enrich is False
    assert evaluate_image_value(chart, repeated=True).category == "repeated"


def test_image_enrichment_recognizes_real_paper_captions():
    cases = [
        ("Figure 2. Overall framework of the proposed method.", "architecture"),
        ("Figure 3. Construction pipeline of the ExpertPool.", "flowchart"),
        (
            "Figure 6. Effect of the dual-pool mechanism on HV convergence.",
            "chart",
        ),
    ]

    for caption, expected_category in cases:
        block = DocumentBlock(
            content=caption,
            block_type=BlockType.IMAGE,
            metadata={
                "bbox": {"l": 80, "t": 700, "r": 520, "b": 400},
            },
        )

        decision = evaluate_image_value(block)

        assert decision.should_enrich is True
        assert decision.category == expected_category


def test_image_enrichment_uses_docling_bbox_to_filter_small_logo():
    logo = DocumentBlock(
        content="[图片]",
        block_type=BlockType.IMAGE,
        metadata={
            "bbox": {"l": 516.65, "t": 804.27, "r": 560.48, "b": 775.31},
        },
    )

    decision = evaluate_image_value(logo)

    assert decision.should_enrich is False
    assert decision.category == "small"


def test_user_can_force_lightweight_pdf_parser():
    profile = DocumentProfile(
        file_ext=".pdf",
        file_size=100,
        scanned_pdf_risk=True,
        features={"advanced_parser_recommended": True},
    )

    selected = ParserRouter().select(profile, "pymupdf")

    assert selected.name == "pymupdf"
    assert profile.features["route_reason"] == "user_selected_pymupdf"


def test_retrieval_evaluation_metrics():
    cases = [
        RetrievalExpectation("问题一", "doc-1", 3),
        RetrievalExpectation("问题二", "doc-2", 5),
    ]
    results = {
        "问题一": [{"source_id": "doc-1", "page_start": 2, "page_end": 3}],
        "问题二": [{"source_id": "other", "page_start": 5, "page_end": 5}],
    }

    metrics = evaluate_retrieval_cases(cases, results, top_k=5)

    assert metrics["case_count"] == 2
    assert metrics["hit_at_k"] == 0.5
    assert metrics["page_accuracy"] == 0.5
