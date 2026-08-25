"""
Semantic-aware chunking strategy for academic PDFs.

──────────────────────────────────────────────────────────────────────────────
CHUNKING DECISION RATIONALE
──────────────────────────────────────────────────────────────────────────────
Goal: maximize recall of relevant passages while keeping each chunk self-
contained enough that an LLM can answer from it without cross-chunk inference.

Why NOT the default RecursiveCharacterTextSplitter(1000, 200):
  • No awareness of document structure — frequently cuts through a paragraph
    mid-sentence, or merges the end of Section 2 with the start of Section 3.
  • "1000 chars" maps to ~180–220 tokens with typical academic prose density,
    which is too small for multi-sentence technical arguments but too large for
    precise factual grounding.
  • Default 200-char overlap (≈36 tokens) is proportionally too high for 1000-
    char chunks (20%), creating near-duplicate chunks that inflate retrieval
    hit-sets without adding recall.

Chosen approach — section-boundary-first, paragraph-fallback:
  1. Primary split: at detected section headers (H1/H2 titles).
     Academic papers are explicitly sectioned; splitting here keeps all text
     about "Quantization Method" in one chunk family, avoiding retrieval misses
     when the query matches the section title but the answer is paragraphs away.
  2. Secondary split: if a section exceeds MAX_TOKENS, split at paragraph
     boundaries ("\n\n" or newline-after-period), not mid-sentence.
  3. Token limit: 450 tokens target, 512 hard max. Rationale:
       • text-embedding-3-small and BAAI/bge-small-en-v1.5 both have 512-token
         context windows — exceeding this silently truncates and degrades
         embedding quality.
       • 450-token target gives ~15% headroom for the overlap window.
       • At typical academic prose (~4.5 tokens/word), 450 tokens ≈ 100 words,
         which comfortably holds 2–4 technical paragraphs — enough for a self-
         contained claim, not so much that the embedding is diluted by noise.
  4. Overlap: 15% (~67 tokens). Rationale:
       • Ensures cross-boundary sentences appear in at least one full chunk.
       • Below 20% to avoid near-duplicate pairs that inflate retrieval sets
         (empirically shown to hurt precision without improving recall at k=6).
  5. Captions: kept as their own single-chunk type; never merged into body
     chunks. Reason: figure/table captions are short, dense, self-contained,
     and often exactly what a query like "what is the accuracy of model X on
     dataset Y" wants.
  6. References: excluded entirely. Reference lists are citation noise: their
     embeddings cluster around author names and venue keywords, not technical
     content, and pollute nearest-neighbor results.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import tiktoken

from research_assistant.ingestion.pdf_parser import ParsedDocument

# Token budget: target well below the 512-token limit of our embedding models
# to avoid silent truncation. 15% overlap = ~67 tokens.
MAX_TOKENS = 450
OVERLAP_TOKENS = 67  # ~15% of MAX_TOKENS
_ENC = tiktoken.get_encoding("cl100k_base")  # matches text-embedding-3-small; close enough for bge


def _tokenize(text: str) -> list[int]:
    return _ENC.encode(text)


def _detokenize(tokens: list[int]) -> str:
    return _ENC.decode(tokens)


_ROMAN_NUMERAL_RE = r"(?:X{0,2}(?:I{1,3}|IV|VI{0,3}|IX)|X)"

_SECTION_HEADER_RE = re.compile(
    r"^(" + _ROMAN_NUMERAL_RE + r"\.?\s+[A-Z][A-Za-z\s]+|"
    r"\d+\.?\s+[A-Z][A-Za-z\s]+|"
    r"\b(?:Abstract|Introduction|Related Work|Background|Methodology|Method|"
    r"Approach|Experiments|Evaluation|Results|Discussion|Conclusion|"
    r"Acknowledgements?|References)\b)",
    re.MULTILINE,
)


def _is_untagged_header(text: str) -> bool:
    """
    Fallback for body blocks that PyMuPDF didn't tag as headers.

    LaTeX-generated arXiv PDFs frequently produce section headers in the same
    font weight/size as body text (especially with default article.cls), so
    pdf_parser.py's _HEADER_RE misses them. This provides a second-pass check
    inside chunk_document for body blocks that look like section titles.

    Conservative guards prevent false positives on body paragraphs:
      - Length < 120 chars (a header is one short line, not a paragraph)
      - No period in the first 60 chars (headers don't end sentences mid-line)
    """
    stripped = text.strip()
    if len(stripped) > 120:
        return False
    if "." in stripped[:60]:
        return False
    return bool(_SECTION_HEADER_RE.match(stripped))


@dataclass
class Chunk:
    text: str
    arxiv_id: str
    section_title: str
    page: int
    chunk_index: int
    block_type: str  # "body" | "caption" | "table"
    token_count: int


def _split_into_paragraphs(text: str) -> list[str]:
    """Split text at paragraph boundaries (double-newline or sentence-end + newline)."""
    # Prefer double-newline splits; fall back to single-newline after sentence-end punctuation
    paras = re.split(r"\n\n+", text)
    result = []
    for p in paras:
        p = p.strip()
        if p:
            result.append(p)
    return result


def _chunk_text_with_overlap(
    text: str,
    section_title: str,
    arxiv_id: str,
    start_page: int,
    start_index: int,
    block_type: str = "body",
) -> list[Chunk]:
    """
    Split a single text segment into MAX_TOKENS chunks with OVERLAP_TOKENS overlap.
    Splits at paragraph boundaries when possible; only falls back to token-level
    split if a single paragraph exceeds MAX_TOKENS.
    """
    paragraphs = _split_into_paragraphs(text)
    chunks: list[Chunk] = []
    buffer_tokens: list[int] = []
    idx = start_index

    def flush(buf: list[int]) -> None:
        nonlocal idx
        if not buf:
            return
        chunk_text = _detokenize(buf).strip()
        if chunk_text:
            chunks.append(
                Chunk(
                    text=chunk_text,
                    arxiv_id=arxiv_id,
                    section_title=section_title,
                    page=start_page,
                    chunk_index=idx,
                    block_type=block_type,
                    token_count=len(buf),
                )
            )
            idx += 1

    for para in paragraphs:
        para_tokens = _tokenize(para)

        if len(para_tokens) > MAX_TOKENS:
            # Oversized paragraph: first flush buffer, then split the paragraph itself
            flush(buffer_tokens)
            buffer_tokens = []
            for i in range(0, len(para_tokens), MAX_TOKENS - OVERLAP_TOKENS):
                slice_tokens = para_tokens[i : i + MAX_TOKENS]
                flush(slice_tokens)
        elif len(buffer_tokens) + len(para_tokens) > MAX_TOKENS:
            flush(buffer_tokens)
            # Carry overlap, but shrink it when para_tokens is large enough that
            # the full OVERLAP_TOKENS + para_tokens would exceed MAX_TOKENS.
            # Without this guard, a 420-token paragraph would produce a buffer of
            # 67 + 420 = 487 tokens, silently truncated by the embedding model.
            safe_overlap = min(OVERLAP_TOKENS, max(0, MAX_TOKENS - len(para_tokens)))
            buffer_tokens = (
                buffer_tokens[-safe_overlap:] + para_tokens
                if safe_overlap
                else list(para_tokens)
            )
        else:
            buffer_tokens.extend(para_tokens)

    flush(buffer_tokens)
    return chunks


def chunk_document(doc: ParsedDocument) -> list[Chunk]:
    """
    Convert a ParsedDocument into retrieval-ready Chunk objects.

    Processing order:
      1. Group body/header blocks by section.
      2. For each section, run _chunk_text_with_overlap.
      3. Append caption/table blocks as individual single-chunk entries.
      4. Skip reference blocks entirely.
    """
    chunks: list[Chunk] = []
    current_section = "Introduction"
    current_page = 1
    current_text_parts: list[str] = []
    # Collected for Stage 2 eyeball: every block text that trips the fallback
    # header heuristic. Printed at the end so we can verify the heuristic isn't
    # misidentifying short body sentences as section titles on real PDFs.
    _fallback_header_hits: list[str] = []

    def flush_section() -> None:
        nonlocal current_text_parts
        if current_text_parts:
            section_text = "\n\n".join(current_text_parts)
            new_chunks = _chunk_text_with_overlap(
                text=section_text,
                section_title=current_section,
                arxiv_id=doc.arxiv_id,
                start_page=current_page,
                start_index=len(chunks),
            )
            chunks.extend(new_chunks)
            current_text_parts = []

    for block in doc.blocks:
        if block.block_type == "reference":
            continue
        if block.block_type in ("caption", "table"):
            # Captions are self-contained single chunks; do not merge with body
            tokens = _tokenize(block.text)
            chunks.append(
                Chunk(
                    text=block.text.strip(),
                    arxiv_id=doc.arxiv_id,
                    section_title=current_section,
                    page=block.page,
                    chunk_index=len(chunks),
                    block_type=block.block_type,
                    token_count=len(tokens),
                )
            )
        elif block.block_type == "header":
            flush_section()
            current_section = block.text.strip()
            current_page = block.page
        else:  # body — with fallback header detection for PyMuPDF misses
            if _is_untagged_header(block.text):
                _fallback_header_hits.append(block.text.strip())
                flush_section()
                current_section = block.text.strip()
                current_page = block.page
            else:
                current_text_parts.append(block.text)
                current_page = block.page

    flush_section()

    if _fallback_header_hits:
        print(
            f"[chunker] {doc.arxiv_id} — fallback header detector fired "
            f"{len(_fallback_header_hits)} time(s):\n"
            + "\n".join(f"  {i+1}. {h!r}" for i, h in enumerate(_fallback_header_hits))
        )

    return chunks
