"""
Golden-file tests for the chunker.

Requirements (Stage 2):
  - Chunk boundaries and counts must be deterministic and asserted, not just "doesn't crash"
  - Demonstrates: clean body chunk, section-spanning chunk, caption chunk
"""

from __future__ import annotations

from research_assistant.ingestion.chunker import chunk_document
from research_assistant.ingestion.pdf_parser import ParsedDocument, TextBlock


def _make_doc(blocks: list[tuple[str, str, int]]) -> ParsedDocument:
    """Helper: (text, block_type, page) → ParsedDocument"""
    doc = ParsedDocument(arxiv_id="test.2024.00001", total_pages=5)
    for text, block_type, page in blocks:
        doc.blocks.append(
            TextBlock(text=text, page=page, block_type=block_type, bbox=(0, 0, 500, 20))
        )
    return doc


SHORT_BODY = "We propose a novel quantization scheme for MCU deployment." * 3
LONG_SECTION = ("Quantization reduces model size by representing weights in lower precision. " * 40)
CAPTION_TEXT = "Figure 1. Accuracy vs. compression ratio on CIFAR-10 for ARM Cortex-M4."


def test_short_body_produces_one_chunk():
    doc = _make_doc([
        ("Introduction", "header", 1),
        (SHORT_BODY, "body", 1),
    ])
    chunks = chunk_document(doc)
    body_chunks = [c for c in chunks if c.block_type == "body"]
    assert len(body_chunks) == 1
    assert chunks[0].section_title == "Introduction"


def test_long_section_splits_into_multiple_chunks():
    doc = _make_doc([
        ("Method", "header", 2),
        (LONG_SECTION, "body", 2),
    ])
    chunks = chunk_document(doc)
    body_chunks = [c for c in chunks if c.block_type == "body"]
    # LONG_SECTION * 40 tokenizes to 481 tokens (measured; BPE merges reduce raw
    # phrase-count math) — provably > MAX_TOKENS=450, triggering the oversized-
    # paragraph split path in _chunk_text_with_overlap.
    assert len(body_chunks) > 1, "Long section must be split into multiple chunks"


def test_caption_becomes_standalone_chunk():
    doc = _make_doc([
        ("Introduction", "header", 1),
        (SHORT_BODY, "body", 1),
        (CAPTION_TEXT, "caption", 2),
    ])
    chunks = chunk_document(doc)
    captions = [c for c in chunks if c.block_type == "caption"]
    assert len(captions) == 1
    assert captions[0].text == CAPTION_TEXT
    # Caption must NOT be merged with any body chunk
    body_texts = [c.text for c in chunks if c.block_type == "body"]
    assert not any(CAPTION_TEXT in t for t in body_texts)


def test_references_excluded():
    doc = _make_doc([
        ("Introduction", "header", 1),
        (SHORT_BODY, "body", 1),
        ("References", "reference", 4),
        ("[1] LeCun, Y. et al. (1998) ...", "reference", 4),
    ])
    chunks = chunk_document(doc)
    assert all(c.block_type != "reference" for c in chunks)


def test_chunk_metadata_populated():
    doc = _make_doc([
        ("Experiments", "header", 3),
        (SHORT_BODY, "body", 3),
    ])
    chunks = chunk_document(doc)
    for c in chunks:
        assert c.arxiv_id == "test.2024.00001"
        assert c.section_title
        assert c.page > 0
        assert c.token_count > 0
        assert c.chunk_index >= 0


def test_chunk_indices_are_monotonic():
    doc = _make_doc([
        ("Method", "header", 1),
        (LONG_SECTION, "body", 1),
    ])
    chunks = chunk_document(doc)
    indices = [c.chunk_index for c in chunks]
    assert indices == sorted(indices)
    assert len(set(indices)) == len(indices), "chunk_index must be unique"


def test_token_count_within_limit():
    from research_assistant.ingestion.chunker import MAX_TOKENS
    doc = _make_doc([
        ("Evaluation", "header", 2),
        (LONG_SECTION * 2, "body", 2),
    ])
    chunks = chunk_document(doc)
    oversized = [c for c in chunks if c.token_count > MAX_TOKENS + 20]  # +20 tolerance for detokenize roundtrip
    assert not oversized, f"Chunks exceed MAX_TOKENS: {[(c.chunk_index, c.token_count) for c in oversized]}"


def test_overlap_carry_does_not_overflow():
    """
    Regression test for the safe_overlap fix in _chunk_text_with_overlap.

    Scenario: para 1 fills the buffer to ~200 tokens; para 2 is ~420 tokens.
    Old code: buffer_tokens = buffer[-67:] + para_tokens → 67 + 420 = 487 > MAX_TOKENS.
    Fixed code: safe_overlap = min(67, 450 - 420) = 30 → 30 + 420 = 450 <= MAX_TOKENS.

    This test would fail (c.token_count == 487) before the safe_overlap fix.
    """
    from research_assistant.ingestion.chunker import (
        MAX_TOKENS,
        _chunk_text_with_overlap,
        _detokenize,
        _tokenize,
    )

    # Build paragraphs using the tokenizer itself so we control token counts precisely.
    # Slicing the token list before decoding gives text whose re-tokenization is
    # approximately the right length; the internal buffer length is what matters for
    # token_count, and that is set by len(buf) — the token list, not a re-tokenization.
    base = (
        "quantization neural network embedded microcontroller model weight inference "
    ) * 65  # measured: 651 tokens at 65 reps (BPE merges make raw phrase-count math wrong)
    base_toks = _tokenize(base)
    assert len(base_toks) >= 650, "base text too short for test"

    # Para 1: ~200 tokens (partial buffer fill)
    para1 = _detokenize(base_toks[:200])
    # Para 2: ~420 tokens — deliberately in the overflow zone.
    # (420 > MAX_TOKENS - OVERLAP_TOKENS = 383, so old code would overflow)
    para2 = _detokenize(base_toks[200:620])

    text = para1 + "\n\n" + para2
    chunks = _chunk_text_with_overlap(
        text=text,
        section_title="Method",
        arxiv_id="test.overflow",
        start_page=2,
        start_index=0,
    )

    assert chunks, "expected at least one chunk"
    oversized = [c for c in chunks if c.token_count > MAX_TOKENS]
    assert not oversized, (
        f"Chunks exceeded MAX_TOKENS={MAX_TOKENS}: "
        f"{[(c.chunk_index, c.token_count) for c in oversized]}"
    )


def test_untagged_header_fallback():
    """
    Verify _is_untagged_header fires for body blocks whose text looks like a
    section title, producing a section boundary even without block_type='header'.
    """
    doc = _make_doc([
        ("Introduction", "header", 1),
        ("We describe our approach.", "body", 1),
        # Untagged header: body block that looks like a section title
        ("Related Work", "body", 2),
        ("Prior work on TinyML includes many approaches.", "body", 2),
    ])
    chunks = chunk_document(doc)
    section_titles = {c.section_title for c in chunks}
    assert "Related Work" in section_titles, (
        "Untagged 'Related Work' body block should be promoted to section title"
    )
    # The body text after it must be in the Related Work section, not Introduction
    rw_chunks = [c for c in chunks if c.section_title == "Related Work" and c.block_type == "body"]
    assert rw_chunks, "Expected body chunks under 'Related Work' section"
    assert any("Prior work" in c.text for c in rw_chunks)
