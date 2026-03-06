"""
Provenance data models and citation resolution for ProtoScore V2.

Every extracted metric links back to source text in the protocol document
via SourceCitation records. This module defines the data structures and
provides fuzzy-match resolution to locate citation bounding boxes in
the parsed document.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import fitz  # PyMuPDF
from PIL import Image
import io


class SourceType(Enum):
    TEXT = "text"
    TABLE_CELL = "table_cell"
    INFERRED = "inferred"


@dataclass
class SourceCitation:
    """A single citation pointing to a location in the source PDF."""
    quote: str
    page_number: int                # 1-indexed
    confidence_score: float         # 0.0 - 1.0
    bbox: Optional[tuple[float, float, float, float]] = None
    source_type: SourceType = SourceType.TEXT
    section_path: list[str] = field(default_factory=list)


@dataclass
class ProvenanceRecord:
    """Complete provenance for a single extracted metric."""
    metric_name: str
    value: int | float | str
    display_label: str
    confidence_score: float         # 0.0 - 1.0
    citations: list[SourceCitation] = field(default_factory=list)
    reasoning: str = ""
    is_estimated: bool = False

    @property
    def needs_review(self) -> bool:
        """Flag for HITL: values with confidence < 0.80 need human review."""
        return self.confidence_score < 0.80


@dataclass
class ExtractionResult:
    """Complete extraction output for a protocol."""
    # V1-compatible dict for the scoring engine
    protocol_data: dict

    # Full provenance keyed by metric_name
    provenance: dict[str, ProvenanceRecord] = field(default_factory=dict)

    # Detailed extraction data for drill-down
    ie_criteria_detail: list[dict] = field(default_factory=list)
    endpoints_detail: list[dict] = field(default_factory=list)
    visit_schedule_detail: list[dict] = field(default_factory=list)

    # Metadata
    source_filename: str = ""
    extraction_timestamp: str = ""
    model_used: str = ""
    total_pages: int = 0


def build_page_index(result: 'ExtractionResult') -> dict[int, list[dict]]:
    """
    Build reverse index: page_number → list of metrics citing that page.

    Used for bidirectional navigation (UX-1.2): when viewing a PDF page,
    shows which metrics reference it.

    Returns:
        Dict mapping page numbers to lists of
        {metric_name, display_label, citation_index, quote_preview}
    """
    index: dict[int, list[dict]] = {}
    for metric_name, record in result.provenance.items():
        for cite_idx, citation in enumerate(record.citations):
            page = citation.page_number
            if page < 1:
                continue
            if page not in index:
                index[page] = []
            # Avoid duplicates (same metric on same page)
            if any(m["metric_name"] == metric_name for m in index[page]):
                continue
            index[page].append({
                "metric_name": metric_name,
                "display_label": record.display_label,
                "citation_index": cite_idx,
                "quote_preview": (citation.quote[:60] + "...") if len(citation.quote) > 60 else citation.quote,
            })
    return index


def resolve_citation(citation: SourceCitation, parsed_doc) -> SourceCitation:
    """
    Given a citation with quote and page_number, find the exact bounding
    box in the ParsedDocument using fuzzy string matching.

    Args:
        citation: SourceCitation with quote and page_number set
        parsed_doc: ParsedDocument from pdf_parser

    Returns:
        SourceCitation with bbox populated if a match was found
    """
    from rapidfuzz import fuzz

    if not citation.quote or citation.page_number < 1:
        return citation

    page_idx = citation.page_number - 1
    if page_idx >= len(parsed_doc.pages):
        return citation

    page = parsed_doc.pages[page_idx]
    best_score = 0.0
    best_bbox = None
    best_source_type = citation.source_type

    # Strategy 1: Search text blocks on the cited page
    for block in page.text_blocks:
        score = fuzz.partial_ratio(citation.quote.lower(), block.text.lower())
        if score > best_score:
            best_score = score
            best_bbox = block.bbox

    # Strategy 2: Search table cells on the cited page
    for table in page.tables:
        for cell in table.cells:
            if cell.text:
                score = fuzz.partial_ratio(citation.quote.lower(), cell.text.lower())
                if score > best_score:
                    best_score = score
                    best_bbox = cell.bbox or table.bbox
                    best_source_type = SourceType.TABLE_CELL

    # Accept match if similarity is above threshold
    if best_score >= 75 and best_bbox:
        citation.bbox = best_bbox
        citation.source_type = best_source_type

    return citation


def resolve_all_citations(result: ExtractionResult, parsed_doc) -> ExtractionResult:
    """Resolve bounding boxes for all citations in an ExtractionResult."""
    for record in result.provenance.values():
        for i, citation in enumerate(record.citations):
            record.citations[i] = resolve_citation(citation, parsed_doc)
    return result


def render_page_with_highlight(
    file_bytes: bytes,
    page_number: int,
    bbox: Optional[tuple[float, float, float, float]] = None,
    margin: int = 50,
    highlight_color: tuple = (0, 163, 224, 60),  # ProtoScore teal, semi-transparent
) -> Image.Image:
    """
    Render a PDF page as an image with an optional highlight rectangle.

    Args:
        file_bytes: Raw PDF bytes
        page_number: 1-indexed page number
        bbox: Optional (x0, y0, x1, y1) bounding box to highlight
        margin: Pixel margin around the highlight for context
        highlight_color: RGBA color for the highlight overlay

    Returns:
        PIL Image of the rendered page
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    page = doc[page_number - 1]

    # Render at 2x resolution for clarity
    mat = fitz.Matrix(2.0, 2.0)

    if bbox:
        # Draw highlight annotation
        rect = fitz.Rect(bbox)
        highlight = page.add_highlight_annot(rect)
        highlight.set_colors(stroke=fitz.utils.getColor("cyan"))
        highlight.update()

    pix = page.get_pixmap(matrix=mat)
    img_data = pix.tobytes("png")
    doc.close()

    return Image.open(io.BytesIO(img_data))
