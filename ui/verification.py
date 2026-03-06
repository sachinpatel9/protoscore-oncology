"""
Batch HITL (Human-in-the-Loop) verification panel for ProtoScore V2.

UX-2.1: All extracted variables in a single tabular view before scoring.
         Bulk-approve high-confidence fields. Review gate blocks scoring
         until all low-confidence fields are resolved.
UX-2.2: Inline source evidence with PDF thumbnails per row.
FR-4.4: Audit log integration for every correction/confirmation.
FR-4.5: Confidence dashboard / Score Reliability indicator.

Design: Warm Clinical / Organic Modern
"""

import base64
import io
from functools import lru_cache

import pandas as pd
from PIL import Image

from logic.provenance import ExtractionResult, ProvenanceRecord
from logic.audit_log import get_verification_stats


# ---------------------------------------------------------------------------
# Editable Fields Mapping
# ---------------------------------------------------------------------------
# Maps provenance metric_name -> (section, key) in protocol_data for writeback.
# Non-editable/derived fields are displayed but edits are ignored.
EDITABLE_FIELDS = {
    "ie_criteria_count": ("complexity_metrics", "ie_criteria_count"),
    "endpoints_count": ("complexity_metrics", "endpoints_count"),
    "total_visits": ("patient_burden", "total_visits"),
    "invasive_procedures": ("patient_burden", "invasive_procedures"),
}


# ---------------------------------------------------------------------------
# Batch Review DataFrame Builder (UX-2.1)
# ---------------------------------------------------------------------------

def build_verification_dataframe(
    result: ExtractionResult,
    verif_state: dict | None = None,
) -> pd.DataFrame:
    """
    Build the batch review DataFrame from extraction provenance.

    Columns: Field Name | Extracted Value | Source Quote | Page |
             Confidence | Status

    Rows are sorted: needs-review (< 0.80) first, then by confidence
    ascending, so the most uncertain fields appear at the top.

    Args:
        result: ExtractionResult from the AI pipeline
        verif_state: Optional verification state dict for status column

    Returns:
        pandas DataFrame for gr.Dataframe display.
    """
    rows = []
    for metric_name, record in result.provenance.items():
        # Skip amendment sub-entries (rolled up into amendment_risk_score)
        if metric_name.startswith("amendment_finding_"):
            continue

        quote = ""
        page = 0
        if record.citations:
            quote = record.citations[0].quote[:150]
            if len(record.citations[0].quote) > 150:
                quote += "..."
            page = record.citations[0].page_number

        # Determine status from verification state
        status = "Pending"
        if verif_state:
            raw_status = verif_state.get("field_status", {}).get(metric_name, "pending")
            status = {
                "pending": "Pending",
                "confirmed": "Confirmed",
                "corrected": "Corrected",
                "bulk_approved": "Approved",
            }.get(raw_status, "Pending")

        rows.append({
            "Field Name": record.display_label,
            "Extracted Value": str(record.value),
            "Source Quote": quote,
            "Page": page,
            "Confidence": round(record.confidence_score, 2),
            "Status": status,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Sort: needs review first (confidence < 0.80), then ascending confidence
    df["_sort_key"] = df["Confidence"].apply(lambda c: 0 if c < 0.80 else 1)
    df = df.sort_values(["_sort_key", "Confidence"]).drop(columns=["_sort_key"])
    df = df.reset_index(drop=True)

    return df


def get_metric_name_order(result: ExtractionResult) -> list[str]:
    """
    Return ordered list of metric names matching DataFrame row order.

    Used to map DataFrame row indices back to provenance keys.
    """
    entries = []
    for metric_name, record in result.provenance.items():
        if metric_name.startswith("amendment_finding_"):
            continue
        entries.append((metric_name, record.confidence_score))

    # Same sort as build_verification_dataframe
    entries.sort(key=lambda e: (0 if e[1] < 0.80 else 1, e[1]))
    return [e[0] for e in entries]


# ---------------------------------------------------------------------------
# Inline Source Evidence (UX-2.2)
# ---------------------------------------------------------------------------

def generate_pdf_thumbnail_b64(
    file_bytes: bytes,
    page_number: int,
    bbox: tuple | None = None,
    zoom: float = 0.5,
) -> str | None:
    """
    Render a PDF page thumbnail at low resolution and return as
    base64-encoded PNG string for embedding in HTML <img> tags.
    """
    try:
        from ui.pdf_viewer import render_pdf_page
        img = render_pdf_page(file_bytes, page_number, bbox, zoom=zoom)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


def generate_pdf_thumbnail_pil(
    file_bytes: bytes,
    page_number: int,
    bbox: tuple | None = None,
    zoom: float = 0.8,
) -> Image.Image | None:
    """
    Render a PDF page thumbnail as a PIL Image for gr.Image display.
    """
    try:
        from ui.pdf_viewer import render_pdf_page
        return render_pdf_page(file_bytes, page_number, bbox, zoom=zoom)
    except Exception:
        return None


def build_inline_evidence_html(
    record: ProvenanceRecord,
    thumbnail_b64: str | None = None,
) -> str:
    """
    Build inline source evidence panel for a selected verification row.

    Shows the full source quote, confidence badge, AI reasoning,
    and optionally an embedded PDF thumbnail (UX-2.2).

    Args:
        record: ProvenanceRecord for the selected metric
        thumbnail_b64: Optional base64-encoded PNG thumbnail

    Returns:
        HTML string for the evidence panel.
    """
    # Confidence badge
    conf = record.confidence_score
    if conf >= 0.85:
        badge_color, badge_label = "#5B7B6F", "HIGH"
    elif conf >= 0.80:
        badge_color, badge_label = "#7A9E8E", "OK"
    elif conf >= 0.60:
        badge_color, badge_label = "#D4A04A", "MEDIUM"
    else:
        badge_color, badge_label = "#C0755B", "LOW"

    needs_review_html = ""
    if record.needs_review:
        needs_review_html = (
            '<div style="background:#C0755B; color:white; padding:4px 12px; '
            'border-radius:8px; font-size:0.8em; font-weight:bold; '
            'margin-top:8px; display:inline-block;">'
            'NEEDS REVIEW (confidence &lt; 0.80)</div>'
        )

    # Source quotes
    quotes_html = ""
    for i, citation in enumerate(record.citations):
        source_type = citation.source_type.value.replace("_", " ").title()
        section = " > ".join(citation.section_path) if citation.section_path else ""

        quotes_html += f"""
        <div style="background:#F0EDE6; padding:10px; border-radius:6px;
                    border-left:3px solid #5B7B6F; margin:6px 0;">
            <div style="font-size:0.7em; color:#9CA3AF; margin-bottom:4px;
                        font-family:'Nunito Sans', sans-serif;">
                Citation {i + 1} · Page {citation.page_number} · {source_type}
                {f' · {section}' if section else ''}
            </div>
            <div style="font-family:'JetBrains Mono', 'Fira Code', monospace; font-size:0.8em; color:#2C2C2C;
                        white-space:pre-wrap; max-height:150px; overflow-y:auto;">
{citation.quote}
            </div>
        </div>
        """

    # AI reasoning
    reasoning_html = ""
    if record.reasoning:
        reasoning_html = f"""
        <div style="background:#F0EDE6; padding:10px; border-radius:6px;
                    margin:8px 0; font-size:0.8em; color:#6B7280;">
            <strong style="color:#5B7B6F;">AI Reasoning:</strong> {record.reasoning}
        </div>
        """

    # Thumbnail
    thumbnail_html = ""
    if thumbnail_b64:
        thumbnail_html = f"""
        <div style="margin-top:10px;">
            <div style="font-size:0.75em; color:#9CA3AF; margin-bottom:4px;">
                PDF Source Page Preview
            </div>
            <img src="data:image/png;base64,{thumbnail_b64}"
                 style="max-width:100%; border:1px solid #E5E0D8; border-radius:6px;"
                 alt="Source page thumbnail" />
        </div>
        """

    return f"""
    <div style="background:#FFFFFF; padding:16px; border-radius:12px;
                border:1px solid #E5E0D8; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="font-size:1.1em; font-weight:600; color:#2C2C2C;
                        font-family:'Nunito Sans', sans-serif;">
                {record.display_label}
            </div>
            <div>
                <span style="background:{badge_color}; color:white; padding:2px 10px;
                             border-radius:10px; font-size:0.75em; font-weight:bold;">
                    {badge_label} ({conf:.0%})
                </span>
            </div>
        </div>

        <div style="font-size:1.4em; font-weight:700; color:#5B7B6F; margin:8px 0;
                    font-family:'Lora', Georgia, serif;">
            {record.value}
        </div>

        {needs_review_html}
        {reasoning_html}

        <div style="font-size:0.8em; color:#6B7280; margin-top:10px; margin-bottom:4px;
                    font-weight:600; font-family:'Nunito Sans', sans-serif;">SOURCE EVIDENCE</div>
        {quotes_html if quotes_html else '<div style="color:#9CA3AF; font-size:0.8em;">No source citations available.</div>'}

        {thumbnail_html}
    </div>
    """


# ---------------------------------------------------------------------------
# Confidence Dashboard (FR-4.5)
# ---------------------------------------------------------------------------

def build_confidence_dashboard_html(verif_state: dict | None) -> str:
    """
    Build the Score Reliability / Confidence Dashboard (FR-4.5).

    Shows percentage breakdown: high-confidence, human-verified, pending.
    Displayed above the batch review table.
    """
    if not verif_state:
        return ""

    stats = get_verification_stats(verif_state)
    total = stats["total"]
    if total == 0:
        return ""

    high_pct = stats["high_confidence_pct"]
    verified_pct = stats["verified_pct"]
    pending_pct = stats["pending_pct"]
    corrections = stats["corrections_count"]

    # Determine grade
    if verified_pct == 100:
        grade, grade_color = "A", "#5B7B6F"
    elif verified_pct >= 80:
        grade, grade_color = "B", "#7A9E8E"
    elif verified_pct >= 50:
        grade, grade_color = "C", "#D4A04A"
    else:
        grade, grade_color = "D", "#C0755B"

    # Calculate bar widths (stacked, total = 100%)
    verified_bar = min(verified_pct, 100)
    pending_bar = min(pending_pct, 100 - verified_bar)

    return f"""
    <div style="background:#FFFFFF; padding:12px 16px; border-radius:12px;
                border:1px solid {grade_color}; margin-bottom:12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div>
                <span style="font-size:0.85em; color:#6B7280; text-transform:uppercase;
                            letter-spacing:1px; font-weight:600;
                            font-family:'Nunito Sans', sans-serif;">Score Reliability</span>
                <span style="font-size:0.7em; color:#9CA3AF; margin-left:8px;">
                    {stats['total']} fields total
                </span>
            </div>
            <div style="display:flex; align-items:center; gap:6px;">
                <span style="font-size:1.8em; font-weight:800; color:{grade_color};
                            font-family:'Lora', Georgia, serif;">{grade}</span>
            </div>
        </div>

        <div style="display:flex; height:8px; border-radius:4px; overflow:hidden;
                    margin:10px 0 6px 0; background:#E5E0D8;">
            <div style="width:{verified_bar}%; background:#5B7B6F;"
                 title="Verified: {verified_pct}%"></div>
            <div style="width:{pending_bar}%; background:#D4A04A;"
                 title="Pending: {pending_pct}%"></div>
        </div>

        <div style="display:flex; justify-content:space-between; font-size:0.7em; color:#9CA3AF;">
            <span style="color:#5B7B6F;">Verified: {verified_pct}%</span>
            <span>High Conf (&#8805;85%): {high_pct}%</span>
            <span style="color:#D4A04A;">Pending: {pending_pct}%</span>
            {f'<span style="color:#5B7B6F;">Corrections: {corrections}</span>' if corrections > 0 else ''}
        </div>
    </div>
    """


# ---------------------------------------------------------------------------
# Review Gate Banner (UX-2.1)
# ---------------------------------------------------------------------------

def build_review_gate_html(verif_state: dict | None) -> str:
    """
    Build HTML showing the review gate status.

    Green banner when all low-confidence fields are resolved.
    Amber/red banner listing which fields still need review.
    """
    if not verif_state:
        return ""

    from logic.audit_log import get_review_gate_status
    is_satisfied, message = get_review_gate_status(verif_state)

    if is_satisfied:
        return f"""
        <div style="background:#F0F8F0; padding:10px 16px; border-radius:8px;
                    border:1px solid #5B7B6F; margin-bottom:8px;">
            <span style="color:#5B7B6F; font-weight:600; font-size:0.85em;
                        font-family:'Nunito Sans', sans-serif;">
                &#10003; {message}
            </span>
        </div>
        """

    return f"""
    <div style="background:#FFF8F0; padding:10px 16px; border-radius:8px;
                border:1px solid #D4A04A; margin-bottom:8px;">
        <span style="color:#D4A04A; font-weight:600; font-size:0.85em;
                    font-family:'Nunito Sans', sans-serif;">
            &#9888; {message}
        </span>
    </div>
    """


# ---------------------------------------------------------------------------
# Apply Verified Values (generic replacement)
# ---------------------------------------------------------------------------

def apply_all_verified_values(
    result: ExtractionResult,
    verif_state: dict,
) -> ExtractionResult:
    """
    Apply ALL verified/corrected values from verification state back into
    the ExtractionResult's protocol_data and provenance records.

    Iterates through EDITABLE_FIELDS and writes back any corrections.
    Non-editable fields are left unchanged.
    """
    current_values = verif_state.get("current_values", {})

    for metric_name, (section, key) in EDITABLE_FIELDS.items():
        if metric_name not in current_values:
            continue

        new_val = current_values[metric_name]

        # Type coerce: values from DataFrame edits come as strings
        original = result.protocol_data.get(section, {}).get(key)
        if isinstance(original, int):
            try:
                new_val = int(float(new_val))
            except (ValueError, TypeError):
                continue
        elif isinstance(original, float):
            try:
                new_val = float(new_val)
            except (ValueError, TypeError):
                continue

        # Write back to protocol_data
        if section in result.protocol_data:
            result.protocol_data[section][key] = new_val

        # Update provenance record value
        if metric_name in result.provenance:
            result.provenance[metric_name].value = new_val

    return result


# ---------------------------------------------------------------------------
# Backward-Compatible Wrappers (deprecated, kept for transition)
# ---------------------------------------------------------------------------

def build_verification_html(result: ExtractionResult) -> str:
    """Legacy: Build basic verification summary HTML."""
    total_metrics = len(result.provenance)
    needs_review = sum(1 for r in result.provenance.values() if r.needs_review)

    status_color = "#5B7B6F" if needs_review == 0 else "#D4A04A"

    return f"""
    <div style="background:#FFFFFF; padding:16px; border-radius:12px;
                border:1px solid #E5E0D8; margin-bottom:16px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <div style="font-size:1.1em; font-weight:600; color:#2C2C2C;
                    font-family:'Nunito Sans', sans-serif;">
            Extraction Verification
        </div>
        <div style="font-size:0.85em; color:#6B7280; margin-top:4px;">
            {total_metrics} metrics extracted &middot;
            <span style="color:{status_color};">{needs_review} need review</span>
        </div>
    </div>
    """


def build_metric_row_html(record: ProvenanceRecord) -> str:
    """Legacy: Build HTML for a single metric verification row."""
    needs_review = record.needs_review
    bg_color = "#FFF8F0" if needs_review else "#FFFFFF"
    border_color = "#D4A04A" if needs_review else "#E5E0D8"

    badge = ""
    if needs_review:
        badge = (
            '<span style="background:#D4A04A; color:white; padding:1px 6px; '
            'border-radius:8px; font-size:0.7em; font-weight:bold;">NEEDS REVIEW</span>'
        )

    quote_html = ""
    if record.citations:
        c = record.citations[0]
        quote_html = f"""
        <div style="font-size:0.75em; color:#6B7280; margin-top:6px;
                    font-style:italic; max-height:60px; overflow:hidden;
                    font-family:'Lora', Georgia, serif;">
            "{c.quote[:200]}{'...' if len(c.quote) > 200 else ''}"
            <span style="color:#9CA3AF;"> — Page {c.page_number}</span>
        </div>
        """

    return f"""
    <div style="background:{bg_color}; padding:12px; border-radius:8px;
                border:1px solid {border_color}; margin:6px 0;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div>
                <span style="font-weight:600; color:#2C2C2C;">
                    {record.display_label}
                </span>
                {badge}
            </div>
            <div style="font-size:0.8em; color:#6B7280;">
                Confidence: {record.confidence_score:.0%}
            </div>
        </div>
        {quote_html}
    </div>
    """


def get_verification_defaults(result: ExtractionResult) -> dict:
    """Legacy: Get default values for verification form fields."""
    defaults = {}
    for name, record in result.provenance.items():
        defaults[name] = record.value
    return defaults


def apply_verified_values(
    result: ExtractionResult,
    ie_count: int,
    endpoints_count: int,
    total_visits: int,
    invasive_procedures: int,
) -> ExtractionResult:
    """Legacy: Apply 4 hardcoded verified values. Use apply_all_verified_values instead."""
    result.protocol_data['complexity_metrics']['ie_criteria_count'] = ie_count
    result.protocol_data['complexity_metrics']['endpoints_count'] = endpoints_count
    result.protocol_data['patient_burden']['total_visits'] = total_visits
    result.protocol_data['patient_burden']['invasive_procedures'] = invasive_procedures

    if "ie_criteria_count" in result.provenance:
        result.provenance["ie_criteria_count"].value = ie_count
    if "endpoints_count" in result.provenance:
        result.provenance["endpoints_count"].value = endpoints_count
    if "total_visits" in result.provenance:
        result.provenance["total_visits"].value = total_visits
    if "invasive_procedures" in result.provenance:
        result.provenance["invasive_procedures"].value = invasive_procedures

    return result
