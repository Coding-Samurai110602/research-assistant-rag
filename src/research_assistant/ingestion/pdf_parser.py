"""
PDF full-text extraction using PyMuPDF.

Handles multi-column academic PDF layout by sorting text blocks by
(column, y-position) rather than raw y-position alone. Reading order:
left column top→bottom, then right column top→bottom.

Extraction produces a structured document with:
  - body_text blocks tagged by detected section
  - figure captions (detected by "Fig." / "Figure" prefix pattern)
  - table content (detected by "Table" prefix)
  - references section (excluded from retrieval chunks — see chunker.py)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf


@dataclass
class TextBlock:
    text: str
    page: int
    block_type: str  # "body" | "caption" | "table" | "header" | "reference"
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1


@dataclass
class ParsedDocument:
    arxiv_id: str
    total_pages: int
    blocks: list[TextBlock] = field(default_factory=list)

    def body_blocks(self) -> list[TextBlock]:
        return [b for b in self.blocks if b.block_type == "body"]

    def caption_blocks(self) -> list[TextBlock]:
        return [b for b in self.blocks if b.block_type == "caption"]

    def reference_blocks(self) -> list[TextBlock]:
        return [b for b in self.blocks if b.block_type == "reference"]


_CAPTION_RE = re.compile(r"^(Fig(?:ure)?\.?\s*\d|Table\s+\d)", re.IGNORECASE)
_TABLE_RE = re.compile(r"^Table\s+\d", re.IGNORECASE)
_HEADER_RE = re.compile(r"^(\d+\.?\s+[A-Z]|\b(?:Abstract|Introduction|Conclusion|References|Related Work|Methodology|Experiments|Results|Evaluation)\b)")
_REFERENCES_RE = re.compile(r"^\s*References\s*$", re.IGNORECASE)


def _classify_block(text: str) -> str:
    stripped = text.strip()
    if _CAPTION_RE.match(stripped):
        return "caption" if not _TABLE_RE.match(stripped) else "table"
    if _HEADER_RE.match(stripped):
        return "header"
    return "body"


def _page_midpoint(page_width: float) -> float:
    return page_width / 2.0


def _sort_blocks_reading_order(blocks: list[dict], page_width: float) -> list[dict]:
    """
    Sort raw PyMuPDF block dicts into correct reading order for two-column layout.

    Algorithm — section-based, not y-merge:
      1. Classify blocks as LEFT (x0 < mid, span ≤ 60% page), RIGHT (x0 ≥ mid,
         span ≤ 60%), or WIDE (span > 60% — titles, captions, section headers).
      2. Sort each bucket by y0.
      3. Wide blocks act as section dividers. Between each pair of consecutive wide
         blocks (and before the first / after the last), emit ALL left-column blocks
         in that y-range top-to-bottom, then ALL right-column blocks top-to-bottom.

    Why NOT a y-merge (the previous approach):
      The y-merge correctly handles wide blocks but interleaves left and right narrow
      blocks by their raw y-coordinate, producing output like:
          RIGHT(y=421) → LEFT(y=434) → RIGHT(y=432) → LEFT(y=512) …
      For two-column prose the correct human reading order is full left column first,
      then full right column — not interleaved by y. The section-based approach
      guarantees this within each "section" (span between full-width elements).

    Edge case — overlapping y-ranges: a right-column block whose y0 is above a
    left-column block in the same section is still emitted AFTER all left-column
    blocks in that section. This matches how a reader actually scans a two-column
    page: finish the left column, then return to the top of the right column.
    """
    mid = _page_midpoint(page_width)
    left, right, wide = [], [], []

    for b in blocks:
        if b.get("type") != 0:  # 0 = text block; skip image blocks (type 1)
            continue
        x0, y0, x1, _ = b["bbox"]
        width = x1 - x0
        if width > page_width * 0.6:
            wide.append(b)
        elif x0 < mid:
            left.append(b)
        else:
            right.append(b)

    left.sort(key=lambda b: b["bbox"][1])
    right.sort(key=lambda b: b["bbox"][1])
    wide.sort(key=lambda b: b["bbox"][1])

    # Section-based ordering:
    #   section_starts[i] / section_ends[i] define the y-interval of section i.
    #   wide[i-1] is inserted between section i-1 and section i (for i ≥ 1).
    #
    #   n_wide = len(wide) → there are (n_wide + 1) sections.
    #   Sections: (-∞, wide[0].y0), (wide[0].y0, wide[1].y0), …, (wide[-1].y0, +∞)
    ordered: list[dict] = []
    n_wide = len(wide)
    section_starts = [float("-inf")] + [b["bbox"][1] for b in wide]
    section_ends   = [b["bbox"][1] for b in wide] + [float("inf")]

    for i in range(n_wide + 1):
        y_lo, y_hi = section_starts[i], section_ends[i]

        # Narrow blocks in this section: left column first, then right column
        sec_left  = [b for b in left  if y_lo <= b["bbox"][1] < y_hi]
        sec_right = [b for b in right if y_lo <= b["bbox"][1] < y_hi]
        ordered.extend(sec_left)
        ordered.extend(sec_right)

        # Append the wide block that follows this section (none after the last section)
        if i < n_wide:
            ordered.append(wide[i])

    return ordered


def parse_pdf(pdf_path: Path, arxiv_id: str) -> ParsedDocument:
    doc = pymupdf.open(str(pdf_path))
    parsed = ParsedDocument(arxiv_id=arxiv_id, total_pages=len(doc))

    in_references = False
    for page_num, page in enumerate(doc, start=1):
        page_rect = page.rect
        raw_blocks = page.get_text("blocks")  # list of (x0,y0,x1,y1,text,block_no,block_type)

        # Convert to dicts for the sort helper
        block_dicts = [
            {"bbox": (b[0], b[1], b[2], b[3]), "text": b[4], "type": b[6]}
            for b in raw_blocks
        ]
        ordered = _sort_blocks_reading_order(block_dicts, page_rect.width)

        for bd in ordered:
            text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", bd["text"] or "").strip()
            if not text or len(text) < 10:
                continue

            if _REFERENCES_RE.match(text):
                in_references = True

            if in_references:
                block_type = "reference"
            else:
                block_type = _classify_block(text)

            parsed.blocks.append(
                TextBlock(
                    text=text,
                    page=page_num,
                    block_type=block_type,
                    bbox=bd["bbox"],
                )
            )

    doc.close()
    return parsed
