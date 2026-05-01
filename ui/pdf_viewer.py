"""
PDF viewer panel for ProtoScore V2 (right side of split-screen).

Renders PDF pages as images with highlight overlays when the user
clicks "Verify" on a metric. Uses PyMuPDF for page rendering.

Design: Clinical Design System
"""

import fitz  # PyMuPDF
import io
from PIL import Image
from typing import Optional

from logic.provenance import ProvenanceRecord, SourceCitation


def render_pdf_page(
    file_bytes: bytes,
    page_number: int,
    highlight_bbox: Optional[tuple[float, float, float, float]] = None,
    zoom: float = 2.0,
) -> Image.Image:
    """
    Render a single PDF page as a PIL Image, optionally with a highlight.

    Args:
        file_bytes: Raw PDF bytes
        page_number: 1-indexed page number
        highlight_bbox: Optional (x0, y0, x1, y1) to highlight
        zoom: Render scale factor (2.0 = 144 DPI)

    Returns:
        PIL Image of the rendered page
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")

    if page_number < 1 or page_number > len(doc):
        # Return a blank image in cool off-white
        doc.close()
        return Image.new("RGB", (800, 100), color=(248, 250, 251))

    page = doc[page_number - 1]

    if highlight_bbox:
        rect = fitz.Rect(highlight_bbox)
        # Add a visible highlight annotation in teal
        annot = page.add_highlight_annot(rect)
        annot.set_colors(stroke=(0.055, 0.486, 0.525))  # Teal #0E7C86
        annot.set_opacity(0.4)
        annot.update()

        # Also draw a border rectangle for visibility
        shape = page.new_shape()
        shape.draw_rect(rect)
        shape.finish(color=(0.055, 0.486, 0.525), width=2)
        shape.commit()

    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    doc.close()

    return Image.open(io.BytesIO(img_bytes))


def get_page_count(file_bytes: bytes) -> int:
    """Get total page count of a PDF."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    count = len(doc)
    doc.close()
    return count


def build_citation_html(citation: SourceCitation) -> str:
    """Build HTML display for a single citation."""
    type_label = citation.source_type.value.replace("_", " ").title()
    section = " > ".join(citation.section_path) if citation.section_path else "—"

    return f"""
    <div style="background:#F0F4F8; padding:12px; border-radius:8px;
                border-left:3px solid #0E7C86; margin:8px 0;">
        <div style="font-size:11px; color:#64748B; margin-bottom:4px;
                    letter-spacing:0.08em; text-transform:uppercase;
                    font-family:'Nunito Sans', sans-serif;">
            Page {citation.page_number} · {type_label} · {section}
        </div>
        <div style="font-family:'JetBrains Mono', 'Fira Code', monospace; font-size:12px; color:#0D1B2A;
                    background:#EDF2F7; padding:8px; border-radius:4px;
                    white-space:pre-wrap; max-height:200px; overflow-y:auto;">
{citation.quote}
        </div>
    </div>
    """


def build_page_context_html(page_number: int, page_index: dict) -> str:
    """
    Build HTML showing which metrics cite the current page (UX-1.2 reverse direction).

    Args:
        page_number: Current PDF page (1-indexed)
        page_index: Output of build_page_index()

    Returns:
        HTML string with metric badges for the current page
    """
    metrics = page_index.get(page_number, [])
    if not metrics:
        return f"""
        <div style="padding:6px; font-size:13px; color:#94A3B8;">
            Page {page_number} — no extracted metrics reference this page.
        </div>
        """

    badges = ""
    for m in metrics:
        badges += (
            f'<span style="background:#0E7C86; color:white; padding:3px 8px; '
            f'border-radius:10px; font-size:0.75em; margin:2px; '
            f'display:inline-block;">{m["display_label"]}</span>'
        )

    return f"""
    <div style="padding:8px; background:#F0F4F8; border-radius:8px; margin-top:4px;">
        <div style="font-size:11px; color:#64748B; margin-bottom:4px;
                    letter-spacing:0.08em; text-transform:uppercase;">
            Page {page_number} — referenced by {len(metrics)} metric(s):
        </div>
        <div>{badges}</div>
    </div>
    """


def build_citation_nav_html(
    metric_label: str,
    citation_index: int,
    total_citations: int,
    citation: Optional[SourceCitation] = None,
) -> str:
    """
    Build HTML showing citation position (e.g., "Citation 1 of 3") and quote preview.

    Args:
        metric_label: Display label of the current metric
        citation_index: 0-based index of the current citation
        total_citations: Total number of citations for this metric
        citation: The current SourceCitation (for quote preview)

    Returns:
        HTML string for the citation navigator
    """
    if total_citations == 0:
        return '<div style="color:#94A3B8; font-size:13px; padding:4px;">No citations available.</div>'

    quote_html = ""
    if citation and citation.quote:
        preview = citation.quote[:100] + ("..." if len(citation.quote) > 100 else "")
        quote_html = f"""
        <div style="font-family:'JetBrains Mono', 'Fira Code', monospace; font-size:12px; color:#64748B;
                    background:#EDF2F7; padding:6px; border-radius:4px;
                    margin-top:4px; white-space:pre-wrap;">{preview}</div>
        """

    page_info = ""
    if citation:
        page_info = f" · Page {citation.page_number}"

    return f"""
    <div style="padding:8px; background:#FFFFFF; border-radius:8px; margin-top:4px;
                border:1px solid #E2E8F0;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-size:13px; color:#0E7C86; font-weight:600;">{metric_label}</span>
            <span style="font-size:12px; color:#64748B;">
                Citation {citation_index + 1} of {total_citations}{page_info}
            </span>
        </div>
        {quote_html}
    </div>
    """


def build_provenance_panel(record: ProvenanceRecord) -> str:
    """Build the full provenance display for a metric."""
    needs_review_badge = ""
    if record.needs_review:
        needs_review_badge = (
            '<span style="background:#C0392B; color:white; padding:2px 8px; '
            'border-radius:10px; font-size:0.75em; margin-left:8px;">NEEDS REVIEW</span>'
        )

    html = f"""
    <div style="padding:12px;">
        <div style="font-size:1.1em; font-weight:600; color:#0D1B2A;
                    font-family:'Nunito Sans', sans-serif;">
            {record.display_label}: <strong style="color:#0E7C86;">{record.value}</strong>
            {needs_review_badge}
        </div>
        <div style="font-size:13px; color:#64748B; margin:4px 0;">
            Confidence: {record.confidence_score:.0%}
            {' · Estimated' if record.is_estimated else ''}
        </div>
    """

    if record.reasoning:
        html += f"""
        <div style="background:#EDF2F7; padding:8px; border-radius:6px;
                    margin:8px 0; font-size:13px; color:#64748B;">
            <strong style="color:#0E7C86;">AI Reasoning:</strong> {record.reasoning}
        </div>
        """

    html += "<div style='margin-top:8px; font-size:13px; color:#64748B;'>Source Evidence:</div>"

    for citation in record.citations:
        html += build_citation_html(citation)

    html += "</div>"
    return html


