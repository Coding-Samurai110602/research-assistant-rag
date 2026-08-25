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
from typing import Any

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
# Roman numerals I–XIX (covers any realistic section count in a paper).
# Case-sensitive by design: "IV." is a section number, "iv." is not.
_ROMAN_NUMERAL_RE = r"(?:X{0,2}(?:I{1,3}|IV|VI{0,3}|IX)|X)"
_HEADER_RE = re.compile(
    r"^(\d+\.?\s+[A-Z]|" + _ROMAN_NUMERAL_RE + r"\.?\s+[A-Z]"
    r"|\b(?:Abstract|Introduction|Conclusion|References|Related Work|"
    r"Methodology|Experiments|Results|Evaluation)\b)"
)
_REFERENCES_RE = re.compile(r"^\s*References\s*$", re.IGNORECASE)
# Matches numbered/Roman headings written entirely in ALL CAPS ("1 INTRODUCTION", "II. METHODS").
_HEADING_ALLCAPS_RE = re.compile(
    r"^(\d+\.?\s+(?:[A-Z][A-Z\-]+\s*)+"
    r"|" + _ROMAN_NUMERAL_RE + r"\.?\s+(?:[A-Z][A-Z\-]+\s*)+)"
)
# Matches section-keyword headings that may be fused with body prose.
_HEADING_KEYWORD_RE = re.compile(
    r"^(Abstract|Introduction|Conclusion|References|Related Work|Methodology|"
    r"Experiments|Results|Evaluation|Background|Discussion|Approach|Method)"
)


def _classify_block(text: str) -> str:
    stripped = text.strip()
    if _CAPTION_RE.match(stripped):
        return "caption" if not _TABLE_RE.match(stripped) else "table"
    if _HEADER_RE.match(stripped):
        # Structural check: a genuine heading is short.  A fused block (heading
        # text + abstract/section body merged by the PDF typesetter into one
        # PyMuPDF block) is always much longer — signal it for splitting so
        # the body prose is not silently swallowed into a section-title string.
        if len(stripped) <= 120:
            return "header"
        return "fused_header"
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


def _split_fused_block(text: str) -> tuple[str, str]:
    """
    Extract (heading, body) from a fused block where a section heading and its
    body prose were merged into one PyMuPDF block by the PDF typesetter.

    Strategies tried in order:
    1. First \\n-delimited line, if short and not sentence-shaped.
    2. ALL-CAPS numbered/Roman prefix ("1 INTRODUCTION body", "II. METHODS body").
    3. Em-dash or double-hyphen separator (IEEE abstract: "Abstract—body").
    4. Keyword heading separated from body by ". ", ": ", or bare whitespace.

    Returns ("", full_text) when no heading is extractable — the caller then
    treats the whole block as body to avoid losing content.
    """
    stripped = text.strip()

    # Strategy 1: first line as heading (must be short and not sentence-shaped)
    if "\n" in stripped:
        first_line, rest = stripped.split("\n", 1)
        first_line = first_line.strip()
        if len(first_line) < 80 and "." not in first_line[:60]:
            return first_line, rest.strip()

    # Strategy 2: numbered/Roman heading with ALL-CAPS words ("1 INTRODUCTION body…")
    m = _HEADING_ALLCAPS_RE.match(stripped)
    if m:
        heading = m.group(0).rstrip()
        body = re.sub(r"^[—:\.\s]+", "", stripped[m.end():]).strip()
        return heading, body

    # Strategy 3: em-dash or double-hyphen separator ("Abstract—body")
    for sep in ["—", "--"]:
        if sep in stripped:
            parts = stripped.split(sep, 1)
            heading = parts[0].strip()
            if len(heading) < 80:
                return heading, parts[1].strip()

    # Strategy 4: keyword heading with ". " or ": " separator within first 60 chars
    m2 = _HEADING_KEYWORD_RE.match(stripped)
    if m2:
        keyword = m2.group(0)
        body = re.sub(r"^[—:\.\s]+", "", stripped[len(keyword):]).strip()
        if len(body) >= 10:
            return keyword, body
        return keyword, ""

    # No reliable split found — preserve everything as body to avoid data loss
    return "", stripped


def parse_pdf(pdf_path: Path, arxiv_id: str) -> ParsedDocument:
    doc = pymupdf.open(str(pdf_path))
    parsed = ParsedDocument(arxiv_id=arxiv_id, total_pages=len(doc))

    in_references = False
    # pymupdf stub doesn't declare Document as Iterable and returns Any for Page attributes;
    # both limitations are stub gaps — iteration and attribute access work correctly at runtime.
    for page_num, page in enumerate(doc, start=1):  # type: ignore[arg-type, var-annotated]
        page_rect: Any = page.rect
        raw_blocks: Any = page.get_text("blocks")  # list of (x0,y0,x1,y1,text,block_no,block_type)

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
                parsed.blocks.append(
                    TextBlock(text=text, page=page_num, block_type="reference", bbox=bd["bbox"])
                )
                continue

            block_type = _classify_block(text)

            if block_type == "fused_header":
                heading, body = _split_fused_block(text)
                if heading:
                    parsed.blocks.append(
                        TextBlock(text=heading, page=page_num, block_type="header", bbox=bd["bbox"])
                    )
                if body and len(body) >= 10:
                    parsed.blocks.append(
                        TextBlock(text=body, page=page_num, block_type="body", bbox=bd["bbox"])
                    )
            else:
                parsed.blocks.append(
                    TextBlock(text=text, page=page_num, block_type=block_type, bbox=bd["bbox"])
                )

    doc.close()
    return parsed
