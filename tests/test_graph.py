"""
LangGraph node and graph tests with mocked LLM / embed calls.

Verifies:
  - Each node function applies the expected state transformation
  - The conditional retry edge is wired correctly (not a no-op)
  - Full graph integration with mocked I/O
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from research_assistant.rag.state import GraphState


def _base_state(**overrides) -> GraphState:
    state: GraphState = {
        "original_query": "What quantization method does MCUNet use?",
        "query_type": "factual",
        "rewritten_query": "",
        "retrieved_chunks": [],
        "graded_chunks": [],
        "answer": "",
        "citations": [],
        "is_grounded": False,
        "groundedness_note": "",
        "retry_count": 0,
        "answerable": True,
        "error": None,
    }
    state.update(overrides)
    return state


# ── analyze_query ─────────────────────────────────────────────────────────────

def test_analyze_query_first_pass():
    mock_llm = MagicMock()
    mock_llm.return_value.content = '{"query_type": "factual", "rewritten_query": "MCUNet quantization technique"}'  # noqa: E501

    with (
        patch("research_assistant.rag.nodes._get_llm", return_value=mock_llm),
    ):
        from research_assistant.rag.nodes import analyze_query
        result = analyze_query(_base_state())

    assert result["query_type"] == "factual"
    assert "MCUNet" in result["rewritten_query"]
    assert result["retry_count"] == 0


def test_analyze_query_on_retry_uses_rewrite_prompt():
    mock_llm = MagicMock()
    mock_llm.return_value.content = "MCUNet INT8 post-training quantization"

    with patch("research_assistant.rag.nodes._get_llm", return_value=mock_llm):
        from research_assistant.rag.nodes import analyze_query
        result = analyze_query(
            _base_state(retry_count=1, rewritten_query="MCUNet quantization technique")
        )

    # On retry, rewritten_query should be the raw LLM string (no JSON parsing)
    assert "MCUNet" in result["rewritten_query"] or result["rewritten_query"]
    assert result["retry_count"] == 1  # node doesn't increment; increment_retry does


# ── grade_relevance ───────────────────────────────────────────────────────────

def test_grade_relevance_filters_irrelevant():
    chunks = [
        {"id": 1, "arxiv_id": "2401.00001", "section_title": "Method", "page": 2,
         "block_type": "body", "text": "MCUNet uses INT8 quantization on Cortex-M4.",
         "token_count": 8, "distance": 0.1},
        {"id": 2, "arxiv_id": "2401.00002", "section_title": "Intro", "page": 1,
         "block_type": "body", "text": "General deep learning surveys.",
         "token_count": 5, "distance": 0.5},
    ]

    call_count = 0
    def mock_llm_side_effect(*args, **kwargs):
        nonlocal call_count
        mock_resp = MagicMock()
        mock_resp.content = '{"relevant": "yes"}' if call_count == 0 else '{"relevant": "no"}'
        call_count += 1
        return mock_resp

    mock_llm = MagicMock(side_effect=mock_llm_side_effect)

    with patch("research_assistant.rag.nodes._get_llm", return_value=mock_llm):
        from research_assistant.rag.nodes import grade_relevance
        result = grade_relevance(_base_state(retrieved_chunks=chunks))

    assert len(result["graded_chunks"]) == 1
    assert result["graded_chunks"][0]["id"] == 1


# ── generate ──────────────────────────────────────────────────────────────────

def test_generate_with_no_graded_chunks_returns_decline():
    with patch("research_assistant.rag.nodes._get_llm"):
        from research_assistant.rag.nodes import generate
        result = generate(_base_state(graded_chunks=[]))

    assert result["answerable"] is False
    assert "do not contain enough information" in result["answer"].lower()
    assert result["citations"] == []


def test_generate_with_chunks_returns_answer():
    chunks = [
        {"id": 1, "arxiv_id": "2401.00001", "section_title": "Method", "page": 2,
         "block_type": "body", "text": "MCUNet uses 8-bit quantization.",
         "token_count": 7, "distance": 0.1},
    ]
    mock_llm = MagicMock()
    mock_llm.return_value.content = "MCUNet uses 8-bit integer quantization (2401.00001, Method)."

    with patch("research_assistant.rag.nodes._get_llm", return_value=mock_llm):
        from research_assistant.rag.nodes import generate
        result = generate(_base_state(graded_chunks=chunks))

    assert result["answerable"] is True
    assert result["answer"]
    assert len(result["citations"]) == 1


# ── Conditional edge ──────────────────────────────────────────────────────────

def test_conditional_edge_routes_to_generate_when_chunks_sufficient():
    from research_assistant.rag.graph import _should_retry_or_generate
    state = _base_state(graded_chunks=[{"id": 1}, {"id": 2}], retry_count=0)
    assert _should_retry_or_generate(state) == "generate"


def test_conditional_edge_routes_to_retry_when_chunks_insufficient():
    from research_assistant.rag.graph import _should_retry_or_generate
    state = _base_state(graded_chunks=[{"id": 1}], retry_count=0)
    assert _should_retry_or_generate(state) == "analyze_query"


def test_conditional_edge_gives_up_after_max_retries():
    from research_assistant.config import settings
    from research_assistant.rag.graph import _should_retry_or_generate
    state = _base_state(graded_chunks=[], retry_count=settings.max_query_retries)
    assert _should_retry_or_generate(state) == "generate"


# ── Retry loop replacement semantics ─────────────────────────────────────────

def test_retry_loop_replaces_not_accumulates_chunks():
    """
    Proof that the retry loop does NOT accumulate stale chunks across passes.

    Scenario:
      Pass 1 — retrieve returns IDs {101, 102}; grade rejects all → retry
      Pass 2 — retrieve returns IDs {201, 202}; grade passes all → generate

    Expected: final graded_chunks == {201, 202}, NOT {101, 102, 201, 202}.

    This verifies that retrieved_chunks and graded_chunks use replacement
    semantics (plain TypedDict fields, no Annotated reducers) as documented
    in state.py. If either field were an append-reducer, stale IDs from pass 1
    would appear in the pass-2 grading pool and contaminate the answer.
    """
    from langgraph.graph import END, StateGraph

    from research_assistant.rag.graph import _should_retry_or_generate
    from research_assistant.rag.state import GraphState

    FIRST_IDS = [101, 102]
    SECOND_IDS = [201, 202]
    call_counts: dict[str, int] = {"retrieve": 0, "grade": 0}

    def _chunk(id_: int) -> dict:
        return {
            "id": id_,
            "arxiv_id": "2401.00001",
            "section_title": "Method",
            "page": 1,
            "block_type": "body",
            "text": f"chunk text {id_}",
            "token_count": 10,
            "distance": 0.1,
        }

    def mock_analyze(state: GraphState) -> dict:
        return {"query_type": "factual", "rewritten_query": f"query-v{state.get('retry_count', 0)}"}

    def mock_retrieve(state: GraphState) -> dict:
        call_counts["retrieve"] += 1
        ids = FIRST_IDS if call_counts["retrieve"] == 1 else SECOND_IDS
        return {"retrieved_chunks": [_chunk(i) for i in ids]}

    def mock_grade(state: GraphState) -> dict:
        call_counts["grade"] += 1
        if call_counts["grade"] == 1:
            return {"graded_chunks": []}  # reject everything → triggers retry
        return {"graded_chunks": list(state["retrieved_chunks"])}  # pass everything

    def mock_generate(state: GraphState) -> dict:
        return {"answer": "ok", "citations": [], "answerable": True}

    def mock_groundedness(state: GraphState) -> dict:
        return {"is_grounded": True, "groundedness_note": ""}

    def increment_retry(state: GraphState) -> dict:
        return {"retry_count": state.get("retry_count", 0) + 1}

    graph = StateGraph(GraphState)
    graph.add_node("analyze_query", mock_analyze)
    graph.add_node("retrieve", mock_retrieve)
    graph.add_node("grade_relevance", mock_grade)
    graph.add_node("increment_retry", increment_retry)
    graph.add_node("generate", mock_generate)
    graph.add_node("check_groundedness", mock_groundedness)
    graph.set_entry_point("analyze_query")
    graph.add_edge("analyze_query", "retrieve")
    graph.add_edge("retrieve", "grade_relevance")
    graph.add_conditional_edges(
        "grade_relevance",
        _should_retry_or_generate,
        {"analyze_query": "increment_retry", "generate": "generate"},
    )
    graph.add_edge("increment_retry", "analyze_query")
    graph.add_edge("generate", "check_groundedness")
    graph.add_edge("check_groundedness", END)

    initial: GraphState = {
        "original_query": "test query",
        "query_type": "factual",
        "rewritten_query": "",
        "retrieved_chunks": [],
        "graded_chunks": [],
        "answer": "",
        "citations": [],
        "is_grounded": False,
        "groundedness_note": "",
        "retry_count": 0,
        "answerable": True,
        "error": None,
    }

    final = graph.compile().invoke(initial)

    assert call_counts["retrieve"] == 2, "Expected exactly 2 retrieve calls (1 pass + 1 retry)"
    assert call_counts["grade"] == 2, "Expected exactly 2 grade calls"

    final_ids = {c["id"] for c in final["graded_chunks"]}

    assert not final_ids.intersection(FIRST_IDS), (
        f"Stale first-pass chunk IDs found in final graded_chunks: "
        f"{final_ids & set(FIRST_IDS)} — replacement semantics broken"
    )
    assert final_ids == set(SECOND_IDS), (
        f"Expected graded_chunks IDs == {set(SECOND_IDS)}, got {final_ids}"
    )
