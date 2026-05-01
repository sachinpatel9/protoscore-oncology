"""
Batch HITL (Human-in-the-Loop) verification panel for ProtoScore V2.

UX-2.1: All extracted variables in a single tabular view before scoring.
         Bulk-approve high-confidence fields. Review gate blocks scoring
         until all low-confidence fields are resolved.
UX-2.2: Inline source evidence with PDF thumbnails per row.
FR-4.4: Audit log integration for every correction/confirmation.
FR-4.5: Confidence dashboard / Score Reliability indicator.

Design: Clinical Design System
"""

import base64
import io

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

# Confidence-based review priority (V2.2 batch verification revamp).
# Thresholds: High < 0.70, Medium [0.70, 0.85), Low >= 0.85.
PRIORITY_RANK = {"High": 0, "Medium": 1, "Low": 2}


def _priority_for(confidence: float) -> tuple[str, str]:
    """Return (label, hex_color) for confidence-based review priority."""
    if confidence < 0.70:
        return ("High", "#C0392B")  # red
    if confidence < 0.85:
        return ("Medium", "#E68A00")  # amber
    return ("Low", "#1A7A45")  # green


def _priority_label_with_dot(confidence: float) -> str:
    """Unicode-dot prefixed label for the gr.Dataframe Priority cell."""
    label, _ = _priority_for(confidence)
    dot = {"High": "\U0001F534", "Medium": "\U0001F7E1", "Low": "\U0001F7E2"}[label]
    return f"{dot} {label}"


def _strip_priority_dot(cell: str) -> str:
    """Reverse of _priority_label_with_dot — extract bare High/Medium/Low."""
    if not isinstance(cell, str):
        return str(cell)
    for key in PRIORITY_RANK:
        if key in cell:
            return key
    return cell


def build_verification_dataframe(
    result: ExtractionResult,
    verif_state: dict | None = None,
    sort_by: str = "priority",
) -> pd.DataFrame:
    """
    Build the batch review DataFrame from extraction provenance.

    Columns: Field Name | Extracted Value | Source Quote | Page |
             Priority | Confidence | Status | Action

    Per V2.1 round 4: the Action column is a real boolean checkbox
    (Gradio `bool` datatype). Confirmed/bulk_approved rows render as
    True (checked); pending/corrected rows render as False (unchecked).
    Toggling the checkbox fires `verification_df.change`, which only
    fires when `interactive=True` — so the per-row approve action is
    naturally gated behind the Edit Report toggle alongside cell edits.

    The Status column maps both "pending" and "corrected" to the
    displayed label "Pending" so an edit visibly reverts a previously
    confirmed row.

    Default sort is "priority" — High → Medium → Low — so the most
    uncertain fields surface at the top. Other sort keys are exposed
    via the Sort dropdown above the dataframe in the Batch Verification
    tab.

    Args:
        result: ExtractionResult from the AI pipeline
        verif_state: Optional verification state dict for status column
        sort_by: One of "priority", "confidence_asc", "confidence_desc",
                 "status", "field_name".

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

        # Determine status from verification state. Note: "corrected" maps to
        # "Pending" for display so an edit reverts a previously confirmed row.
        # The audit log retains the "corrected" distinction underneath.
        raw_status = "pending"
        if verif_state:
            raw_status = verif_state.get("field_status", {}).get(metric_name, "pending")
        status = {
            "pending": "Pending",
            "confirmed": "Confirmed",
            "corrected": "Pending",
            "bulk_approved": "Confirmed",
        }.get(raw_status, "Pending")

        # Action column: bool checkbox for per-row approval (V2.1 r4).
        # True = confirmed/bulk_approved; False = pending/corrected.
        action = raw_status in ("confirmed", "bulk_approved")

        rows.append({
            "Field Name": record.display_label,
            "Extracted Value": str(record.value),
            "Source Quote": quote,
            "Page": page,
            "Priority": _priority_label_with_dot(record.confidence_score),
            "Confidence": round(record.confidence_score, 2),
            "Status": status,
            "Action": action,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = _sort_verification_df(df, sort_by)
    df = df.reset_index(drop=True)
    return df


def _sort_verification_df(df: pd.DataFrame, sort_by: str) -> pd.DataFrame:
    """Apply a sort_by key to the verification dataframe."""
    if df.empty:
        return df

    key = (sort_by or "priority").lower()
    if key == "priority":
        df = df.assign(
            _prio=df["Priority"].map(lambda c: PRIORITY_RANK.get(_strip_priority_dot(c), 99))
        )
        df = df.sort_values(["_prio", "Confidence"]).drop(columns=["_prio"])
    elif key in ("confidence_asc", "confidence (low → high)"):
        df = df.sort_values("Confidence", ascending=True)
    elif key in ("confidence_desc", "confidence (high → low)"):
        df = df.sort_values("Confidence", ascending=False)
    elif key == "status":
        df = df.sort_values("Status")
    elif key in ("field_name", "field name (a → z)"):
        df = df.sort_values("Field Name")
    else:
        df = df.assign(
            _prio=df["Priority"].map(lambda c: PRIORITY_RANK.get(_strip_priority_dot(c), 99))
        )
        df = df.sort_values(["_prio", "Confidence"]).drop(columns=["_prio"])
    return df


# Map dropdown labels → sort_by keys understood by build_verification_dataframe.
SORT_LABEL_TO_KEY = {
    "Priority (High → Low)": "priority",
    "Confidence (Low → High)": "confidence_asc",
    "Confidence (High → Low)": "confidence_desc",
    "Status": "status",
    "Field Name (A → Z)": "field_name",
}


def get_metric_name_order(
    result: ExtractionResult,
    sort_by: str = "priority",
) -> list[str]:
    """
    Return ordered list of metric names matching DataFrame row order.

    Used to map DataFrame row indices back to provenance keys.
    """
    entries = []
    for metric_name, record in result.provenance.items():
        if metric_name.startswith("amendment_finding_"):
            continue
        label, _ = _priority_for(record.confidence_score)
        entries.append((metric_name, record.confidence_score, label, record.display_label))

    key = (sort_by or "priority").lower()
    if key == "priority":
        entries.sort(key=lambda e: (PRIORITY_RANK.get(e[2], 99), e[1]))
    elif key in ("confidence_asc", "confidence (low → high)"):
        entries.sort(key=lambda e: e[1])
    elif key in ("confidence_desc", "confidence (high → low)"):
        entries.sort(key=lambda e: -e[1])
    elif key in ("field_name", "field name (a → z)"):
        entries.sort(key=lambda e: e[3])
    else:
        entries.sort(key=lambda e: (PRIORITY_RANK.get(e[2], 99), e[1]))
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
        badge_color, badge_label = "#1A7A45", "HIGH"
    elif conf >= 0.80:
        badge_color, badge_label = "#3A9CA5", "OK"
    elif conf >= 0.60:
        badge_color, badge_label = "#E68A00", "MEDIUM"
    else:
        badge_color, badge_label = "#C0392B", "LOW"

    needs_review_html = ""
    if record.needs_review:
        needs_review_html = (
            '<div style="background:#C0392B; color:white; padding:4px 12px; '
            'border-radius:8px; font-size:13px; font-weight:bold; '
            'margin-top:8px; display:inline-block;">'
            'NEEDS REVIEW (confidence &lt; 0.80)</div>'
        )

    # Source quotes
    quotes_html = ""
    for i, citation in enumerate(record.citations):
        source_type = citation.source_type.value.replace("_", " ").title()
        section = " > ".join(citation.section_path) if citation.section_path else ""

        quotes_html += f"""
        <div style="margin:6px 0;">
            <div style="font-size:11px; color:#94A3B8; margin-bottom:4px;
                        letter-spacing:0.08em; text-transform:uppercase;
                        font-family:'Nunito Sans', sans-serif;">
                Citation {i + 1} · Page {citation.page_number} · {source_type}
                {f' · {section}' if section else ''}
            </div>
            <blockquote style="border-left:3px solid #0E7C86; background:#F0F9FA;
                               padding:12px; margin:0; border-radius:0 6px 6px 0;
                               font-size:13px; font-family:'JetBrains Mono', 'Fira Code', monospace;
                               color:#0D1B2A; white-space:pre-wrap; max-height:150px;
                               overflow-y:auto;">
{citation.quote}
            </blockquote>
        </div>
        """

    # AI reasoning
    reasoning_html = ""
    if record.reasoning:
        reasoning_html = f"""
        <div style="background:#EDF2F7; padding:10px; border-radius:6px;
                    margin:8px 0; font-size:13px; color:#64748B;">
            <strong style="color:#0E7C86;">AI Reasoning:</strong> {record.reasoning}
        </div>
        """

    # Thumbnail
    thumbnail_html = ""
    if thumbnail_b64:
        thumbnail_html = f"""
        <div style="margin-top:10px;">
            <div style="margin-bottom:6px;">
                <span style="color:#0E7C86; font-size:13px; font-weight:600;
                             cursor:pointer;">Jump to Source in PDF &#x2192;</span>
            </div>
            <img src="data:image/png;base64,{thumbnail_b64}"
                 style="max-width:100%; border:1px solid #E2E8F0; border-radius:6px;"
                 alt="Source page thumbnail" />
        </div>
        """

    return f"""
    <div style="background:#FFFFFF; padding:16px; border-radius:12px;
                border:1px solid #E2E8F0; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="font-size:1.1em; font-weight:600; color:#0D1B2A;
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

        <div style="font-size:1.4em; font-weight:700; color:#0E7C86; margin:8px 0;
                    font-family:'Lora', Georgia, serif;">
            {record.value}
        </div>

        {needs_review_html}
        {reasoning_html}

        <div style="font-size:11px; color:#64748B; margin-top:10px; margin-bottom:4px;
                    font-weight:600; letter-spacing:0.08em; text-transform:uppercase;
                    font-family:'Nunito Sans', sans-serif;">SOURCE EVIDENCE</div>
        {quotes_html if quotes_html else '<div style="color:#94A3B8; font-size:13px;">No source citations available.</div>'}

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

    mean_conf_pct = stats["mean_confidence_pct"]
    verified_pct = stats["verified_pct"]
    pending_pct = stats["pending_pct"]
    corrections = stats["corrections_count"]

    bars = [
        ("Reliability Confidence", mean_conf_pct, "#0E7C86"),
        ("Verified Extraction Values", verified_pct, "#1A7A45"),
        ("Pending Confirmation Extracted Values", pending_pct, "#E68A00"),
    ]

    bar_rows = "".join(
        f"""
        <div class="score-reliability-row">
            <div class="score-reliability-label">{label}</div>
            <div class="score-reliability-bar-track"
                 style="background:#E2E8F0; height:6px; border-radius:4px; overflow:hidden;
                        box-shadow: inset 0 1px 2px rgba(0,0,0,0.08);">
                <div class="score-reliability-bar-fill"
                     style="width:{pct}%; background:{color}; height:100%;
                            border-radius:4px; transition: width 0.4s ease-out;"></div>
            </div>
            <div class="score-reliability-pct"
                 style="color:{color}; font-family:'JetBrains Mono','Fira Code',monospace;
                        font-size:13px; font-weight:700; text-align:right; min-width:44px;">{pct}%</div>
        </div>
        """
        for label, pct, color in bars
    )

    corrections_html = ""
    if corrections > 0:
        corrections_html = (
            f'<span style="color:#0E7C86; margin-left:8px;">'
            f'&middot; {corrections} correction{"s" if corrections != 1 else ""}</span>'
        )

    return f"""
    <div style="background:#FFFFFF; padding:16px; border-radius:12px;
                border:1px solid #E2E8F0; margin-bottom:12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <div style="display:flex; justify-content:space-between; align-items:center;
                    margin-bottom:12px;">
            <span style="font-size:11px; color:#64748B; text-transform:uppercase;
                        letter-spacing:0.08em; font-weight:600;
                        font-family:'Nunito Sans', sans-serif;">Score Reliability</span>
            <span style="font-size:11px; color:#94A3B8;">
                {stats['total']} fields total{corrections_html}
            </span>
        </div>
        {bar_rows}
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
        <div style="background:#F0FDF4; padding:10px 16px; border-radius:8px;
                    border:1px solid #1A7A45; margin-bottom:8px;">
            <span style="color:#1A7A45; font-weight:600; font-size:13px;
                        font-family:'Nunito Sans', sans-serif;">
                &#10003; {message}
            </span>
        </div>
        """

    return f"""
    <div style="background:#FFFBF0; padding:10px 16px; border-radius:8px;
                border:1px solid #E68A00; margin-bottom:8px;">
        <span style="color:#E68A00; font-weight:600; font-size:13px;
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

    status_color = "#1A7A45" if needs_review == 0 else "#E68A00"

    return f"""
    <div style="background:#FFFFFF; padding:16px; border-radius:12px;
                border:1px solid #E2E8F0; margin-bottom:16px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <div style="font-size:1.1em; font-weight:600; color:#0D1B2A;
                    font-family:'Nunito Sans', sans-serif;">
            Extraction Verification
        </div>
        <div style="font-size:13px; color:#64748B; margin-top:4px;">
            {total_metrics} metrics extracted &middot;
            <span style="color:{status_color};">{needs_review} need review</span>
        </div>
    </div>
    """


def build_metric_row_html(record: ProvenanceRecord) -> str:
    """Legacy: Build HTML for a single metric verification row."""
    needs_review = record.needs_review
    bg_color = "#FFFBF0" if needs_review else "#FFFFFF"
    border_color = "#E68A00" if needs_review else "#E2E8F0"

    badge = ""
    if needs_review:
        badge = (
            '<span style="background:#E68A00; color:white; padding:1px 6px; '
            'border-radius:8px; font-size:0.7em; font-weight:bold;">NEEDS REVIEW</span>'
        )

    quote_html = ""
    if record.citations:
        c = record.citations[0]
        quote_html = f"""
        <div style="font-size:12px; color:#64748B; margin-top:6px;
                    font-style:italic; max-height:60px; overflow:hidden;
                    font-family:'Lora', Georgia, serif;">
            "{c.quote[:200]}{'...' if len(c.quote) > 200 else ''}"
            <span style="color:#94A3B8;"> — Page {c.page_number}</span>
        </div>
        """

    return f"""
    <div style="background:{bg_color}; padding:12px; border-radius:8px;
                border:1px solid {border_color}; margin:6px 0;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div>
                <span style="font-weight:600; color:#0D1B2A;">
                    {record.display_label}
                </span>
                {badge}
            </div>
            <div style="font-size:13px; color:#64748B;">
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
