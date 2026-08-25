"""
arXiv ingestion client.

Implements Stage 1 requirements:
- Queries arXiv API (export.arxiv.org/api/query), no auth needed
- 3-second minimum delay between requests (arXiv usage policy)
- Exponential backoff on download failures
- Writes data/metadata.json with full paper metadata
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import requests

from research_assistant.config import settings

# Namespace used in arXiv Atom feed
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"
PDF_DIR = DATA_DIR / "raw_pdfs"
METADATA_PATH = DATA_DIR / "metadata.json"


@dataclass
class PaperMetadata:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published: str
    categories: list[str]
    arxiv_url: str
    local_path: str
    download_date: str


def search_arxiv(query: str, max_results: int = 5, start: int = 0) -> list[dict]:
    """Return raw Atom entries from arXiv for a given query string."""
    url = "http://export.arxiv.org/api/query"
    params = {
        "search_query": query,
        "max_results": max_results,
        "start": start,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    entries = []
    for entry in root.findall("atom:entry", _NS):
        arxiv_id_raw = entry.findtext("atom:id", default="", namespaces=_NS)
        arxiv_id = arxiv_id_raw.split("/abs/")[-1].strip()

        title = (
            entry.findtext("atom:title", default="", namespaces=_NS) or ""
        ).replace("\n", " ").strip()
        abstract = (
            entry.findtext("atom:summary", default="", namespaces=_NS) or ""
        ).replace("\n", " ").strip()
        published = entry.findtext("atom:published", default="", namespaces=_NS) or ""

        authors = [
            a.findtext("atom:name", default="", namespaces=_NS) or ""
            for a in entry.findall("atom:author", _NS)
        ]
        categories = [
            t.get("term", "")
            for t in entry.findall("atom:category", _NS)
        ]

        entries.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "published": published,
                "categories": categories,
                "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",
            }
        )
    return entries


def download_pdf(arxiv_id: str, dest_dir: Path, max_retries: int = 3) -> Path:
    """Download arXiv PDF with exponential backoff. Returns local path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    dest = dest_dir / f"{arxiv_id.replace('/', '_')}.pdf"

    if dest.exists():
        return dest

    for attempt in range(max_retries):
        try:
            resp = requests.get(pdf_url, timeout=60, stream=True)
            resp.raise_for_status()
            with dest.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return dest
        except requests.RequestException as exc:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt * settings.arxiv_request_delay_seconds
            print(f"  Retry {attempt + 1}/{max_retries} for {arxiv_id} after {wait:.0f}s: {exc}")
            time.sleep(wait)

    raise RuntimeError(f"Failed to download {arxiv_id} after {max_retries} attempts")


# TinyML-focused search queries (Stage 1 requirement: on-topic papers only)
TINYML_QUERIES = [
    "ti:TinyML OR ti:tiny machine learning",
    "ti:microcontroller neural network inference",
    "ti:ARM Cortex-M machine learning",
    "ti:quantized neural network embedded",
    "ti:ESP32 deep learning",
    "ti:MCU neural network deployment",
    "ti:edge inference quantization",
]


def run_ingestion(max_per_query: int = 3, output_dir: Path = DATA_DIR) -> list[PaperMetadata]:
    """
    Run the full ingestion pipeline:
    1. Search arXiv with TinyML-targeted queries
    2. Deduplicate by arxiv_id
    3. Download PDFs (3s delay between requests, per arXiv policy)
    4. Write metadata.json
    """
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    seen: dict[str, dict] = {}
    for query in TINYML_QUERIES:
        print(f"\nSearching: {query}")
        try:
            results = search_arxiv(query, max_results=max_per_query)
        except Exception as exc:
            print(f"  Search failed: {exc}")
            results = []

        for r in results:
            if r["arxiv_id"] not in seen:
                seen[r["arxiv_id"]] = r
                print(f"  Found: {r['arxiv_id']} — {r['title'][:80]}")

        time.sleep(settings.arxiv_request_delay_seconds)

    papers: list[PaperMetadata] = []
    for raw in seen.values():
        print(f"\nDownloading PDF: {raw['arxiv_id']}")
        try:
            local_path = download_pdf(raw["arxiv_id"], PDF_DIR)
            papers.append(
                PaperMetadata(
                    arxiv_id=raw["arxiv_id"],
                    title=raw["title"],
                    authors=raw["authors"],
                    abstract=raw["abstract"],
                    published=raw["published"],
                    categories=raw["categories"],
                    arxiv_url=raw["arxiv_url"],
                    local_path=str(local_path),
                    download_date=datetime.utcnow().isoformat(),
                )
            )
            print(f"  OK → {local_path.name}")
        except Exception as exc:
            print(f"  SKIP {raw['arxiv_id']}: {exc}")

        time.sleep(settings.arxiv_request_delay_seconds)

    metadata_path = output_dir / "metadata.json"
    with metadata_path.open("w") as f:
        json.dump([asdict(p) for p in papers], f, indent=2)
    print(f"\nWrote {len(papers)} papers to {metadata_path}")
    return papers
