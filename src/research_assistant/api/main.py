from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from research_assistant.api.routes import router

app = FastAPI(
    title="TinyML Research Assistant",
    description="RAG over arXiv TinyML papers — LangGraph + pgvector",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
