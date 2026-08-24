from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from research_assistant.core import RAGResponse, answer_question, list_ingested_papers

router = APIRouter()


class QueryRequest(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("question must not be empty")
        return v.strip()


class CitationOut(BaseModel):
    arxiv_id: str
    title: str
    section_title: str
    page: int
    chunk_id: int


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    retrieved_chunk_ids: list[int]
    retry_count: int
    answerable: bool
    is_grounded: bool
    groundedness_note: str
    query_type: str
    rewritten_query: str


class PaperOut(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    published: str
    categories: list[str]
    arxiv_url: str


@router.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    try:
        result: RAGResponse = answer_question(request.question)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return QueryResponse(
        answer=result.answer,
        citations=[CitationOut(**c) for c in result.citations],
        retrieved_chunk_ids=result.retrieved_chunk_ids,
        retry_count=result.retry_count,
        answerable=result.answerable,
        is_grounded=result.is_grounded,
        groundedness_note=result.groundedness_note,
        query_type=result.query_type,
        rewritten_query=result.rewritten_query,
    )


@router.get("/papers", response_model=list[PaperOut])
def papers() -> list[PaperOut]:
    try:
        result = list_ingested_papers()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return [PaperOut(**vars(p)) for p in result]
