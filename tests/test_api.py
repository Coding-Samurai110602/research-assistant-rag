"""
FastAPI REST API tests.

All calls to core.answer_question and core.list_ingested_papers are mocked —
no DB or LLM calls in CI.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from research_assistant.api.main import app
from research_assistant.core import PaperSummary, RAGResponse

client = TestClient(app)

MOCK_RESPONSE = RAGResponse(
    answer="MCUNet uses INT8 quantization targeting Cortex-M4.",
    citations=[
        {
            "arxiv_id": "2401.00001",
            "title": "MCUNet: Tiny Deep Learning on IoT Devices",
            "section_title": "Method",
            "page": 3,
            "chunk_id": 42,
        }
    ],
    retrieved_chunk_ids=[42],
    retry_count=0,
    answerable=True,
    is_grounded=True,
    groundedness_note="",
    query_type="factual",
    rewritten_query="MCUNet quantization technique ARM Cortex-M4",
)

MOCK_PAPERS = [
    PaperSummary(
        arxiv_id="2401.00001",
        title="MCUNet: Tiny Deep Learning on IoT Devices",
        authors=["Ji Lin", "Wei-Ming Chen"],
        published="2020-07-20T00:00:00",
        categories=["cs.LG", "cs.AR"],
        arxiv_url="https://arxiv.org/abs/2007.10319",
    )
]


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_query_success():
    with patch("research_assistant.api.routes.answer_question", return_value=MOCK_RESPONSE):
        resp = client.post("/query", json={"question": "What quantization does MCUNet use?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["answerable"] is True
    assert "citations" in data
    assert data["citations"][0]["arxiv_id"] == "2401.00001"


def test_query_empty_question_rejected():
    resp = client.post("/query", json={"question": "   "})
    assert resp.status_code == 422  # pydantic validation error


def test_query_missing_body():
    resp = client.post("/query", json={})
    assert resp.status_code == 422


def test_papers_list():
    with patch("research_assistant.api.routes.list_ingested_papers", return_value=MOCK_PAPERS):
        resp = client.get("/papers")
    assert resp.status_code == 200
    papers = resp.json()
    assert len(papers) == 1
    assert papers[0]["arxiv_id"] == "2401.00001"


def test_query_core_exception_returns_500():
    with patch(
        "research_assistant.api.routes.answer_question",
        side_effect=RuntimeError("DB down"),
    ):
        resp = client.post("/query", json={"question": "anything"})
    assert resp.status_code == 500
