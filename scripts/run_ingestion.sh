#!/usr/bin/env bash
# Download TinyML arXiv papers and embed + store chunks in pgvector.
# Run AFTER setup_db.sh and after docker-compose is up.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$ROOT_DIR"

echo "=== Stage 1: arXiv download ==="
python -c "
from research_assistant.ingestion.arxiv_client import run_ingestion
papers = run_ingestion()
print(f'Downloaded {len(papers)} papers')
"

echo ""
echo "=== Stage 2-3: Parse, chunk, embed, store ==="
python -c "
import json
from pathlib import Path
from sqlalchemy.orm import Session
from research_assistant.ingestion.arxiv_client import PaperMetadata
from research_assistant.ingestion.pdf_parser import parse_pdf
from research_assistant.ingestion.chunker import chunk_document
from research_assistant.db.vector_store import get_engine, insert_paper, insert_chunks, _get_embedding_fn

metadata_path = Path('data/metadata.json')
papers = [PaperMetadata(**p) for p in json.loads(metadata_path.read_text())]

engine = get_engine()
embed_fn = _get_embedding_fn()

for meta in papers:
    print(f'Processing: {meta.arxiv_id} — {meta.title[:60]}')
    parsed = parse_pdf(Path(meta.local_path), meta.arxiv_id)
    chunks = chunk_document(parsed)
    print(f'  {len(chunks)} chunks from {parsed.total_pages} pages')

    with Session(engine) as session:
        paper = insert_paper(session, meta)
        insert_chunks(session, paper, chunks, embed_fn)
        session.commit()
    print(f'  Stored in pgvector')

print('Ingestion complete.')
"
