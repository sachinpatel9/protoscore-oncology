"""
ProtoScore Oncology V2 — Protocol Complexity Analyst

Gradio application with split-screen layout:
  Left:  Complexity Scorecard (PCS score, metric cards, radar chart, formula)
  Right: PDF Viewer with click-to-verify source highlighting

Two modes:
  - Upload Protocol: AI-powered extraction from PDF/Word documents
  - Demo Protocols: Pre-loaded sample protocols with varied complexity
"""

import os
import io
import traceback
from pathlib import Path

import gradio as gr
import plotly.graph_objects as go
import pandas as pd
from dotenv import load_dotenv
from PIL import Image

from logic.data_manager import load_demo_data, load_from_extraction, get_protocol_details
from logic.scoring import calculate_pcs, format_score_formula, format_amendment_risk_formula
from logic.provenance import ExtractionResult, resolve_all_citations, build_page_index
from logic.pdf_parser import parse_protocol_pdf, parse_protocol_docx
from logic.ai_extractor import ExtractionPipeline, OllamaExtractionPipeline
from logic.ollama_utils import (
    check_ollama_running,
    get_installed_models,
    get_ollama_status_html,
    get_system_ram_gb,
    pull_model,
    recommend_model,
)
from ui.layout import CUSTOM_CSS, HEADER_HTML
from logic.enrollment_projector import project_enrollment
from ui.scorecard import (
    render_scorecard, build_radar_chart, build_formula_display,
    build_amendment_formula_display, build_enrollment_formula_display,
    build_enhancement_formula_display,
)
from ui.pdf_viewer import (
    render_pdf_page, build_provenance_panel,
    build_page_context_html, build_citation_nav_html,
)
from ui.verification import (
    build_verification_html, build_metric_row_html,
    apply_verified_values, get_verification_defaults,
    # New batch HITL verification (UX-2.1, UX-2.2, FR-4.4, FR-4.5)
    build_verification_dataframe, get_metric_name_order,
    build_inline_evidence_html, generate_pdf_thumbnail_pil,
    generate_pdf_thumbnail_b64, build_confidence_dashboard_html,
    build_review_gate_html, apply_all_verified_values,
    EDITABLE_FIELDS,
)
from logic.audit_log import (
    init_verification_state, record_correction, record_confirmation,
    bulk_approve_high_confidence, get_review_gate_status,
    export_audit_log_json, get_verification_stats,
)
from ui.progress import build_progress_html
from ui.export import generate_pdf_report

# Load environment variables
load_dotenv()

# Default scoring weights
DEFAULT_WEIGHTS = {"complexity": 0.4, "patient": 0.3, "site": 0.3}


# ---------------------------------------------------------------------------
# Demo Mode Handlers
# ---------------------------------------------------------------------------

def get_demo_options():
    """Return list of demo protocol IDs for the dropdown."""
    df = load_demo_data()
    return df["id"].tolist()


def run_demo_analysis(protocol_id: str):
    """Score a demo protocol and return all display components."""
    df = load_demo_data()
    protocol = get_protocol_details(df, protocol_id)

    score_result = calculate_pcs(protocol, DEFAULT_WEIGHTS)
    formula = format_score_formula(protocol, DEFAULT_WEIGHTS)

    scorecard_html = render_scorecard(score_result, protocol, formula)
    radar_fig = build_radar_chart(score_result["breakdown"], protocol["name"])

    # Amendment risk formula
    amendment_data = protocol.get("amendment_risk", {})
    amendment_formula = format_amendment_risk_formula(amendment_data) if amendment_data else None
    formula_html = build_formula_display(formula)
    if amendment_formula:
        formula_html += build_amendment_formula_display(amendment_formula)

    # Enrollment projection formula
    enrollment_data = protocol.get("enrollment_projection", {})
    if enrollment_data:
        formula_html += build_enrollment_formula_display(enrollment_data)

    # Enhanced Pillars A/B/C formula
    if any(protocol.get(k) for k in ("procedure_weight_summary", "burden_spikes", "population_impacts", "sequencing_risks")):
        formula_html += build_enhancement_formula_display(protocol)

    # Insights panel
    insights = protocol.get("rwd_insights", [])
    insights_html = '<div style="padding:8px;">'
    for insight in insights:
        insights_html += f"""
        <div style="background:#FFF8F0; padding:10px; border-radius:8px;
                    border-left:3px solid #D4A04A; margin:8px 0;
                    font-size:0.85em; color:#2C2C2C;">
            {insight}
        </div>
        """
    insights_html += "</div>"

    # Protocol info
    info_html = f"""
    <div style="font-size:0.85em; color:#6B7280; padding:8px;">
        <strong style="color:#2C2C2C;">{protocol['name']}</strong><br>
        Phase {protocol['phase']} · {protocol.get('therapeutic_area', 'Oncology')}<br>
        {protocol.get('study_design', '')}
    </div>
    """

    return scorecard_html, radar_fig, formula_html, insights_html, info_html


# ---------------------------------------------------------------------------
# Upload Mode Handlers
# ---------------------------------------------------------------------------

def run_extraction(file_path, llm_provider, progress=gr.Progress()):
    """
    Run the full extraction pipeline on an uploaded document.

    Returns a tuple of display components for both the Assessment Dashboard
    and the Batch Verification tab.
    """
    use_ollama = llm_provider == "Ollama (Local)"

    # 12-element error tuple matching outputs
    error_tuple = (
        None, None, "", None, "",
        None, "",
        # Batch verification outputs
        None, pd.DataFrame(), "", "", "",
    )

    if not use_ollama:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return error_tuple[:6] + (
                "ANTHROPIC_API_KEY not found. Please set it in your .env file.",
            ) + error_tuple[7:]

    if use_ollama and not check_ollama_running():
        return error_tuple[:6] + (
            "Ollama is not running. Install from [ollama.com](https://ollama.com), "
            "then run `ollama serve`.",
        ) + error_tuple[7:]

    try:
        file_bytes = Path(file_path).read_bytes()
        filename = Path(file_path).name

        is_word = filename.lower().endswith((".docx", ".doc"))

        # Step 1: Parse document
        progress(0.10, desc="Parsing document...")
        if is_word:
            parsed_doc = parse_protocol_docx(file_bytes)
        else:
            parsed_doc = parse_protocol_pdf(file_bytes)

        # Step 2: Run extraction pipeline with progress callback
        def progress_cb(step: str, fraction: float):
            progress(fraction, desc=step)

        if use_ollama:
            installed = get_installed_models()
            model, tier, rationale = recommend_model(installed)

            if model not in installed:
                progress(0.12, desc=f"Pulling {model} (best for your system)...")
                success = pull_model(
                    model,
                    progress_callback=lambda msg, frac: progress(
                        0.12 + frac * 0.08, desc=msg
                    ),
                )
                if not success:
                    return error_tuple[:6] + (
                        f"Failed to pull model `{model}`. "
                        f"Try manually: `ollama pull {model}`",
                    ) + error_tuple[7:]

            pipeline = OllamaExtractionPipeline(model, parsed_doc)
        else:
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            pipeline = ExtractionPipeline(api_key, parsed_doc)

        result = pipeline.run(progress_callback=progress_cb)
        result.source_filename = filename
        result.total_pages = parsed_doc.total_pages

        # Step 3: Resolve citation bounding boxes
        progress(0.98, desc="Resolving source citations...")
        result = resolve_all_citations(result, parsed_doc)

        # Step 4: Initialize verification state (FR-4.4, UX-2.1)
        verif_state = init_verification_state(result.provenance)

        # Step 5: Score (initial, before user verification)
        score_result = calculate_pcs(result.protocol_data, DEFAULT_WEIGHTS)
        formula = format_score_formula(result.protocol_data, DEFAULT_WEIGHTS)

        scorecard_html = render_scorecard(
            score_result, result.protocol_data, formula, result.provenance,
            verif_state=verif_state,
        )
        radar_fig = build_radar_chart(score_result["breakdown"], filename)

        # Amendment risk formula
        amendment_data = result.protocol_data.get("amendment_risk", {})
        amendment_formula = format_amendment_risk_formula(amendment_data) if amendment_data else None
        formula_html = build_formula_display(formula)
        if amendment_formula:
            formula_html += build_amendment_formula_display(amendment_formula)

        # Enrollment projection formula
        enrollment_data = result.protocol_data.get("enrollment_projection", {})
        if enrollment_data:
            formula_html += build_enrollment_formula_display(enrollment_data)

        # Enhanced Pillars A/B/C formula
        if any(result.protocol_data.get(k) for k in ("procedure_weight_summary", "burden_spikes", "population_impacts", "sequencing_risks")):
            formula_html += build_enhancement_formula_display(result.protocol_data)

        # Render first PDF page
        page_img = None
        if not is_word:
            page_img = render_pdf_page(file_bytes, 1)

        # Step 6: Build batch verification table (UX-2.1)
        batch_df = build_verification_dataframe(result, verif_state)
        confidence_dashboard = build_confidence_dashboard_html(verif_state)
        review_gate = build_review_gate_html(verif_state)

        progress(1.0, desc="Extraction complete.")

        return (
            result,                 # extraction state
            file_bytes,             # uploaded file bytes state
            scorecard_html,         # scorecard
            radar_fig,              # radar chart
            formula_html,           # formula display
            page_img,               # first PDF page
            "",                     # no error
            # Batch verification outputs
            verif_state,            # verification state
            batch_df,               # batch review dataframe
            confidence_dashboard,   # confidence dashboard HTML
            review_gate,            # review gate HTML
            "",                     # inline evidence (empty initially)
        )

    except Exception as e:
        error_msg = f"Extraction failed: {str(e)}"
        return error_tuple[:6] + (error_msg,) + error_tuple[7:]


# ---------------------------------------------------------------------------
# Batch HITL Verification Handlers (UX-2.1, UX-2.2, FR-4.4)
# ---------------------------------------------------------------------------

def on_batch_row_select(evt: gr.SelectData, result_state, file_bytes_state):
    """
    When user clicks a row in the batch verification table, show inline
    source evidence with PDF thumbnail (UX-2.2).

    Returns: (inline_evidence_html, evidence_thumbnail_image)
    """
    empty = (
        '<div style="color:#9CA3AF; padding:20px;">Select a row to see source evidence.</div>',
        None,
    )

    if result_state is None or not isinstance(result_state, ExtractionResult):
        return empty

    # Get row index from selection event
    row_idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index

    # Map row index to metric name using sorted order
    metric_order = get_metric_name_order(result_state)
    if row_idx < 0 or row_idx >= len(metric_order):
        return empty

    metric_name = metric_order[row_idx]
    record = result_state.provenance.get(metric_name)
    if not record:
        return empty

    # Generate PDF thumbnail for inline evidence
    thumbnail_b64 = None
    thumbnail_pil = None
    if record.citations and file_bytes_state is not None:
        citation = record.citations[0]
        if citation.page_number >= 1:
            thumbnail_b64 = generate_pdf_thumbnail_b64(
                file_bytes_state, citation.page_number, citation.bbox
            )
            thumbnail_pil = generate_pdf_thumbnail_pil(
                file_bytes_state, citation.page_number, citation.bbox
            )

    evidence_html = build_inline_evidence_html(record, thumbnail_b64)
    return evidence_html, thumbnail_pil


def on_batch_df_change(df, verif_state, result_state):
    """
    When user edits a cell in the batch verification DataFrame,
    detect changes and record corrections in the audit log (FR-4.4).

    Returns: (updated_df, updated_verif_state, dashboard_html, gate_html)
    """
    if verif_state is None or result_state is None:
        return df, verif_state, "", ""

    metric_order = get_metric_name_order(result_state)

    # Iterate rows and detect value changes
    for idx, row in df.iterrows():
        if idx >= len(metric_order):
            continue

        metric_name = metric_order[idx]
        new_val_str = str(row.get("Extracted Value", ""))
        original_val = verif_state["original_values"].get(metric_name)
        current_val = verif_state["current_values"].get(metric_name)

        # Only track changes for editable fields
        if metric_name not in EDITABLE_FIELDS:
            # Revert non-editable fields to original value
            if str(original_val) != new_val_str:
                df.at[idx, "Extracted Value"] = str(original_val)
            continue

        # Check if value changed from current tracked value
        if new_val_str != str(current_val):
            verif_state = record_correction(verif_state, metric_name, new_val_str)
            df.at[idx, "Status"] = "Corrected"

    # Rebuild dashboard and gate
    dashboard_html = build_confidence_dashboard_html(verif_state)
    gate_html = build_review_gate_html(verif_state)

    return df, verif_state, dashboard_html, gate_html


def on_confirm_selected_field(df, verif_state, result_state):
    """
    Confirm the currently visible fields that are still pending.
    Since gr.Dataframe doesn't track a single "selected" row persistently,
    this confirms all pending fields that haven't been modified.

    Returns: (updated_df, updated_verif_state, dashboard_html, gate_html)
    """
    if verif_state is None or result_state is None:
        return df, verif_state, "", ""

    metric_order = get_metric_name_order(result_state)

    # Find first pending low-confidence field and confirm it
    for idx, metric_name in enumerate(metric_order):
        status = verif_state["field_status"].get(metric_name, "pending")
        confidence = verif_state["confidence_scores"].get(metric_name, 1.0)

        if status == "pending" and confidence < 0.80:
            verif_state = record_confirmation(verif_state, metric_name)
            if idx < len(df):
                df.at[idx, "Status"] = "Confirmed"
            break  # Confirm one at a time

    dashboard_html = build_confidence_dashboard_html(verif_state)
    gate_html = build_review_gate_html(verif_state)

    return df, verif_state, dashboard_html, gate_html


def on_bulk_approve(df, verif_state, result_state):
    """
    Bulk-approve all pending fields with confidence >= 0.85 (UX-2.1).

    Returns: (updated_df, updated_verif_state, dashboard_html, gate_html)
    """
    if verif_state is None:
        return df, verif_state, "", ""

    verif_state = bulk_approve_high_confidence(verif_state, threshold=0.85)

    # Update DataFrame status column to match
    if result_state is not None:
        metric_order = get_metric_name_order(result_state)
        for idx, metric_name in enumerate(metric_order):
            status = verif_state["field_status"].get(metric_name, "pending")
            if idx < len(df):
                df.at[idx, "Status"] = {
                    "pending": "Pending",
                    "confirmed": "Confirmed",
                    "corrected": "Corrected",
                    "bulk_approved": "Approved",
                }.get(status, "Pending")

    dashboard_html = build_confidence_dashboard_html(verif_state)
    gate_html = build_review_gate_html(verif_state)

    return df, verif_state, dashboard_html, gate_html


def on_confirm_and_score(result_state, verif_state):
    """
    Apply verified values and recalculate PCS — with review gate enforcement.

    The review gate blocks scoring if any field with confidence < 0.80
    has not been explicitly confirmed or corrected (UX-2.1 constraint).

    Returns: (result, scorecard_html, radar_fig, formula_html, gate_html)
    """
    if result_state is None:
        return None, "", None, "", ""

    if verif_state is None:
        return result_state, "", None, "", ""

    # Review gate check (UX-2.1)
    is_satisfied, message = get_review_gate_status(verif_state)
    if not is_satisfied:
        gate_html = f"""
        <div style="background:#FFF5F5; padding:12px 16px; border-radius:8px;
                    border:1px solid #C0755B; margin-bottom:8px;">
            <span style="color:#C0755B; font-weight:600; font-size:0.85em;">
                &#10007; Cannot score yet: {message}
            </span>
        </div>
        """
        return result_state, "", None, "", gate_html

    # Apply all corrections from verification state
    result = apply_all_verified_values(result_state, verif_state)

    # Recalculate PCS
    score_result = calculate_pcs(result.protocol_data, DEFAULT_WEIGHTS)
    formula = format_score_formula(result.protocol_data, DEFAULT_WEIGHTS)

    scorecard_html = render_scorecard(
        score_result, result.protocol_data, formula, result.provenance,
        verif_state=verif_state,
    )
    radar_fig = build_radar_chart(score_result["breakdown"], result.source_filename)

    # Full formula display with all pillars
    formula_html = build_formula_display(formula)

    amendment_data = result.protocol_data.get("amendment_risk", {})
    if amendment_data:
        amendment_formula = format_amendment_risk_formula(amendment_data)
        if amendment_formula:
            formula_html += build_amendment_formula_display(amendment_formula)

    enrollment_data = result.protocol_data.get("enrollment_projection", {})
    if enrollment_data:
        formula_html += build_enrollment_formula_display(enrollment_data)

    if any(result.protocol_data.get(k) for k in ("procedure_weight_summary", "burden_spikes", "population_impacts", "sequencing_risks")):
        formula_html += build_enhancement_formula_display(result.protocol_data)

    gate_html = build_review_gate_html(verif_state)

    return result, scorecard_html, radar_fig, formula_html, gate_html


def on_export_audit_log(verif_state, result_state):
    """
    Export audit log as JSON file for regulatory download (FR-4.4).

    Returns: gr.File update with the JSON file path.
    """
    import tempfile

    if verif_state is None:
        return gr.update(visible=False)

    protocol_name = ""
    if result_state is not None and isinstance(result_state, ExtractionResult):
        protocol_name = result_state.source_filename

    json_str = export_audit_log_json(verif_state, protocol_name)

    # Write to temp file for download
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="protoscore_audit_",
        delete=False,
    )
    tmp.write(json_str)
    tmp.close()

    return gr.update(value=tmp.name, visible=True)


def on_export_pdf(result_state, verif_state, demo_selector_value, mode_value):
    """
    Generate and return a PDF report for download (UX-3.1, UX-3.2).

    Works in both upload mode (with provenance/verification) and
    demo mode (protocol data only).
    """
    from ui.scorecard import build_radar_chart

    # Determine data source
    if mode_value == "Upload Protocol" and result_state is not None:
        protocol_data = result_state.protocol_data
        provenance = result_state.provenance
        protocol_name = result_state.source_filename
    else:
        df = load_demo_data()
        protocol = get_protocol_details(df, demo_selector_value)
        protocol_data = dict(protocol)
        provenance = None
        verif_state = None
        protocol_name = protocol_data.get("name", "Demo Protocol")

    # Calculate scores
    score_result = calculate_pcs(protocol_data, DEFAULT_WEIGHTS)
    formula = format_score_formula(protocol_data, DEFAULT_WEIGHTS)

    # Build radar chart
    radar_fig = build_radar_chart(score_result["breakdown"], protocol_name)

    # Generate PDF
    pdf_path = generate_pdf_report(
        protocol_data=protocol_data,
        score_result=score_result,
        formula=formula,
        radar_fig=radar_fig,
        provenance=provenance,
        verif_state=verif_state,
        protocol_name=protocol_name,
    )

    return gr.update(value=pdf_path, visible=True)


def view_source(result_state, metric_key, file_bytes_state):
    """Show provenance panel and highlighted PDF page for a metric."""
    if result_state is None or not isinstance(result_state, ExtractionResult):
        return "<div style='color:#9CA3AF; padding:8px;'>No extraction data available.</div>", None

    record = result_state.provenance.get(metric_key)
    if not record:
        return "<div style='color:#9CA3AF; padding:8px;'>No provenance for this metric.</div>", None

    provenance_html = build_provenance_panel(record)

    page_img = None
    if record.citations and file_bytes_state is not None:
        citation = record.citations[0]
        try:
            page_img = render_pdf_page(
                file_bytes_state, citation.page_number, citation.bbox
            )
        except Exception:
            pass

    return provenance_html, page_img


# ---------------------------------------------------------------------------
# Bidirectional Navigation Handlers (UX-1.2)
# ---------------------------------------------------------------------------

def navigate_to_metric(result_state, metric_key, file_bytes_state):
    """
    Dashboard: jump PDF viewer to a metric's source citation.

    Direction 1: Scorecard → PDF (UX-1.2).
    Returns updated PDF image, page number, page context, citation nav, evidence panel, citation index.
    """
    empty = (None, 1, "", "", "", 0)

    if result_state is None or not isinstance(result_state, ExtractionResult):
        return empty

    record = result_state.provenance.get(metric_key)
    if not record or not record.citations:
        no_data = (
            '<div style="color:#9CA3AF; font-size:0.85em; padding:8px;">'
            f'No source citations for "{metric_key}".</div>'
        )
        return (None, 1, "", "", no_data, 0)

    citation = record.citations[0]
    page_index = build_page_index(result_state)

    # Render highlighted PDF page
    page_img = None
    if file_bytes_state is not None and citation.page_number >= 1:
        try:
            page_img = render_pdf_page(
                file_bytes_state, citation.page_number, citation.bbox
            )
        except Exception:
            pass

    page_context = build_page_context_html(citation.page_number, page_index)
    cite_nav = build_citation_nav_html(
        record.display_label, 0, len(record.citations), citation
    )
    evidence = build_provenance_panel(record)

    return (page_img, citation.page_number, page_context, cite_nav, evidence, 0)


def nav_page_with_context(file_bytes_state, current_page, direction, result_state):
    """
    Enhanced page navigation that also updates page context panel.

    Direction 2: PDF → Scorecard context (UX-1.2).
    """
    if file_bytes_state is None:
        return None, current_page, ""

    new_page = max(1, int(current_page) + direction)
    page_context = ""

    try:
        img = render_pdf_page(file_bytes_state, new_page)
    except Exception:
        return None, current_page, ""

    if result_state is not None and isinstance(result_state, ExtractionResult):
        page_index = build_page_index(result_state)
        page_context = build_page_context_html(new_page, page_index)

    return img, new_page, page_context


def cycle_citation(result_state, metric_key, current_cite_idx, direction, file_bytes_state):
    """
    Move to the next/previous citation for the currently selected metric.

    Returns updated PDF image, page number, page context, citation nav, evidence, new citation index.
    """
    empty = (None, 1, "", "", "", 0)

    if result_state is None or not isinstance(result_state, ExtractionResult):
        return empty

    record = result_state.provenance.get(metric_key)
    if not record or not record.citations:
        return empty

    total = len(record.citations)
    new_idx = (int(current_cite_idx) + direction) % total
    citation = record.citations[new_idx]
    page_index = build_page_index(result_state)

    page_img = None
    if file_bytes_state is not None and citation.page_number >= 1:
        try:
            page_img = render_pdf_page(
                file_bytes_state, citation.page_number, citation.bbox
            )
        except Exception:
            pass

    page_context = build_page_context_html(citation.page_number, page_index)
    cite_nav = build_citation_nav_html(
        record.display_label, new_idx, total, citation
    )
    evidence = build_provenance_panel(record)

    return (page_img, citation.page_number, page_context, cite_nav, evidence, new_idx)


def get_metric_choices(result_state):
    """Build metric choices for the dashboard navigator from provenance keys."""
    if result_state is None or not isinstance(result_state, ExtractionResult):
        return gr.update(choices=[], value=None)

    choices = []
    for metric_name, record in result_state.provenance.items():
        if record.citations:
            choices.append((record.display_label, metric_name))
    return gr.update(choices=choices, value=choices[0][1] if choices else None)


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

def run_simulator(protocol_id, new_visits, new_biopsies, current_mode, result_state):
    """Run what-if simulation with adjusted parameters."""
    if current_mode == "Upload Protocol" and result_state is not None:
        protocol_data = {
            "complexity_metrics": dict(result_state.protocol_data["complexity_metrics"]),
            "patient_burden": dict(result_state.protocol_data["patient_burden"]),
            "site_burden": dict(result_state.protocol_data["site_burden"]),
        }
    else:
        df = load_demo_data()
        protocol = get_protocol_details(df, protocol_id)
        protocol_data = {
            "complexity_metrics": dict(protocol["complexity_metrics"]),
            "patient_burden": dict(protocol["patient_burden"]),
            "site_burden": dict(protocol["site_burden"]),
        }

    original_score = calculate_pcs(protocol_data, DEFAULT_WEIGHTS)

    modified = {
        "complexity_metrics": dict(protocol_data["complexity_metrics"]),
        "patient_burden": dict(protocol_data["patient_burden"]),
        "site_burden": dict(protocol_data["site_burden"]),
    }
    modified["patient_burden"]["total_visits"] = int(new_visits)
    modified["patient_burden"]["invasive_procedures"] = int(new_biopsies)
    new_score = calculate_pcs(modified, DEFAULT_WEIGHTS)

    delta = round(new_score["total"] - original_score["total"], 1)
    delta_sign = "+" if delta > 0 else ""
    delta_color = "#C0755B" if delta > 0 else "#5B7B6F" if delta < 0 else "#9CA3AF"

    html = f"""
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:12px;">
        <div style="background:#FFFFFF; padding:20px; border-radius:12px; text-align:center;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.06); border:1px solid #E5E0D8;">
            <div style="color:#6B7280; font-size:0.85em; font-family:'Nunito Sans', sans-serif;">Current Score</div>
            <div style="font-size:2.5em; font-weight:700; color:#5B7B6F;
                        font-family:'Lora', Georgia, serif;">
                {original_score['total']:.1f}
            </div>
        </div>
        <div style="background:#FFFFFF; padding:20px; border-radius:12px; text-align:center;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.06); border:1px solid #E5E0D8;">
            <div style="color:#6B7280; font-size:0.85em; font-family:'Nunito Sans', sans-serif;">Simulated Score</div>
            <div style="font-size:2.5em; font-weight:700; color:{delta_color};
                        font-family:'Lora', Georgia, serif;">
                {new_score['total']:.1f}
            </div>
            <div style="font-size:1em; color:{delta_color};">
                {delta_sign}{delta}
            </div>
        </div>
    </div>
    """

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=["Current", "Simulated"],
        y=[original_score["total"], new_score["total"]],
        marker_color=["#5B7B6F", delta_color],
        text=[f"{original_score['total']:.1f}", f"{new_score['total']:.1f}"],
        textposition="auto",
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#4B5563", family="Nunito Sans"),
        yaxis=dict(range=[0, 100], gridcolor="#E5E0D8"),
        height=300,
        margin=dict(l=40, r=40, t=20, b=40),
    )

    return html, fig


def run_enrollment_calculator(num_sites, target_n, current_mode, result_state, protocol_id):
    """Calculate time-to-full-enrollment with sensitivity table (FR-E6.4)."""
    num_sites = int(num_sites)
    target_n = int(target_n)

    if num_sites <= 0 or target_n <= 0:
        return '<div style="color:#9CA3AF; padding:8px;">Enter valid number of sites and target enrollment.</div>'

    # Get enrollment rate from current context
    enrollment_data = None
    if current_mode == "Upload Protocol" and result_state is not None:
        enrollment_data = result_state.protocol_data.get("enrollment_projection", {})
    else:
        df = load_demo_data()
        protocol = get_protocol_details(df, protocol_id)
        enrollment_data = protocol.get("enrollment_projection", {})

    if not enrollment_data:
        return '<div style="color:#9CA3AF; padding:8px;">No enrollment projection available. Analyze a protocol first.</div>'

    rate = enrollment_data.get("rate_per_site_per_month", 0)
    ci = enrollment_data.get("confidence_interval_80", [0, 0])

    if rate <= 0:
        return '<div style="color:#9CA3AF; padding:8px;">Enrollment rate is zero. Cannot calculate timeline.</div>'

    # Base estimate
    base_months = target_n / (rate * num_sites)

    # Sensitivity table (±20% variance per FR-E6.4)
    scenarios = [
        ("Pessimistic (-20%)", rate * 0.8),
        ("Base Case", rate),
        ("Optimistic (+20%)", rate * 1.2),
        ("Lower CI", ci[0]),
        ("Upper CI", ci[1]),
    ]

    rows_html = ""
    for label, adj_rate in scenarios:
        if adj_rate > 0:
            months = target_n / (adj_rate * num_sites)
            color = "#5B7B6F" if months <= 18 else "#D4A04A" if months <= 30 else "#C0755B"
        else:
            months = float("inf")
            color = "#C0755B"
        months_str = f"{months:.1f}" if months != float("inf") else "N/A"
        rows_html += f"""
        <tr>
            <td style="padding:8px; color:#2C2C2C;">{label}</td>
            <td style="padding:8px; color:#6B7280; text-align:center;">{adj_rate:.2f}</td>
            <td style="padding:8px; color:{color}; text-align:center; font-weight:600;">{months_str}</td>
        </tr>
        """

    return f"""
    <div style="background:#FFFFFF; padding:16px; border-radius:12px; margin-top:8px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06); border:1px solid #E5E0D8;">
        <div style="font-size:0.85em; color:#6B7280; font-weight:600; text-transform:uppercase;
                    letter-spacing:1px; margin-bottom:12px;
                    font-family:'Nunito Sans', sans-serif;">Time-to-Full-Enrollment Estimate</div>
        <div style="display:flex; justify-content:space-around; margin-bottom:16px;">
            <div style="text-align:center;">
                <div style="font-size:0.75em; color:#6B7280;">Projected Rate</div>
                <div style="font-size:1.6em; font-weight:700; color:#5B7B6F;
                            font-family:'Lora', Georgia, serif;">{rate}</div>
                <div style="font-size:0.7em; color:#9CA3AF;">pts/site/month</div>
            </div>
            <div style="text-align:center;">
                <div style="font-size:0.75em; color:#6B7280;">Sites × Target</div>
                <div style="font-size:1.6em; font-weight:700; color:#2C2C2C;">{num_sites} × {target_n}</div>
            </div>
            <div style="text-align:center;">
                <div style="font-size:0.75em; color:#6B7280;">Est. Duration</div>
                <div style="font-size:1.6em; font-weight:700; color:{'#5B7B6F' if base_months <= 18 else '#D4A04A' if base_months <= 30 else '#C0755B'};
                            font-family:'Lora', Georgia, serif;">{base_months:.1f}</div>
                <div style="font-size:0.7em; color:#9CA3AF;">months</div>
            </div>
        </div>
        <div style="font-size:0.8em; color:#6B7280; margin-bottom:6px; font-weight:600;">SENSITIVITY TABLE</div>
        <table style="width:100%; border-collapse:collapse; font-size:0.85em;">
            <tr style="border-bottom:1px solid #E5E0D8;">
                <th style="padding:8px; color:#6B7280; text-align:left;">Scenario</th>
                <th style="padding:8px; color:#6B7280; text-align:center;">Rate (pts/site/mo)</th>
                <th style="padding:8px; color:#6B7280; text-align:center;">Months to Full</th>
            </tr>
            {rows_html}
        </table>
        <div style="font-size:0.7em; color:#9CA3AF; margin-top:8px; font-style:italic;">
            Formula: months = target_N / (rate × num_sites)
        </div>
    </div>
    """


# ---------------------------------------------------------------------------
# Build Gradio App
# ---------------------------------------------------------------------------

def build_app():
    with gr.Blocks(
        title="ProtoScore Oncology V2",
    ) as app:

        # --- State ---
        extraction_state = gr.State(None)
        uploaded_file_state = gr.State(None)
        citation_index_state = gr.State(0)
        verification_state = gr.State(None)

        # --- Header ---
        gr.HTML(HEADER_HTML)

        # --- Mode Selection ---
        mode = gr.Radio(
            ["Upload Protocol", "Demo Protocols"],
            value="Demo Protocols",
            label="Mode",
            interactive=True,
        )

        # =================================================================
        # UPLOAD MODE SECTION
        # =================================================================
        with gr.Group(visible=False) as upload_section:
            file_upload = gr.File(
                label="Upload Protocol (PDF or Word)",
                file_types=[".pdf", ".docx", ".doc"],
                type="filepath",
            )
            with gr.Row():
                llm_provider = gr.Dropdown(
                    choices=["Claude API", "Ollama (Local)"],
                    value="Claude API",
                    label="LLM Provider",
                    interactive=True,
                    scale=1,
                )
                analyze_btn = gr.Button(
                    "Analyze Protocol",
                    variant="primary",
                    size="lg",
                    scale=1,
                )
            ollama_status = gr.HTML("", visible=False)
            error_display = gr.Markdown("")

        # =================================================================
        # DEMO MODE SECTION
        # =================================================================
        with gr.Group(visible=True) as demo_section:
            demo_selector = gr.Dropdown(
                choices=get_demo_options(),
                value=get_demo_options()[0],
                label="Select Demo Protocol",
                interactive=True,
            )
            demo_info = gr.HTML("")

        # =================================================================
        # MAIN TABS
        # =================================================================
        with gr.Tabs():

            # --- Tab 1: Assessment Dashboard (Split-Screen) ---
            with gr.Tab("Assessment Dashboard"):
                with gr.Row(equal_height=False):
                    # LEFT: Scorecard
                    with gr.Column(scale=1):
                        scorecard_html = gr.HTML("")
                        radar_chart = gr.Plot(label="Multi-Dimensional Risk")
                        formula_html = gr.HTML("")

                        # PDF Export (UX-3.1, UX-3.2)
                        with gr.Row():
                            export_pdf_btn = gr.Button(
                                "Export PDF Report",
                                variant="primary",
                                size="sm",
                            )
                        pdf_download = gr.File(
                            label="PDF Report Download",
                            visible=False,
                        )

                        # Bidirectional Navigation: metric selector (UX-1.2)
                        gr.Markdown("### Navigate to Source")
                        dashboard_metric_selector = gr.Radio(
                            choices=[],
                            label="Select metric to jump to its source in the PDF",
                            interactive=True,
                        )

                    # RIGHT: PDF Viewer
                    with gr.Column(scale=1):
                        pdf_page_display = gr.Image(
                            label="Protocol PDF",
                            type="pil",
                            height=600,
                        )
                        with gr.Row():
                            page_nav_prev = gr.Button("< Prev", size="sm", scale=1)
                            page_num_display = gr.Number(
                                label="Page", value=1, minimum=1,
                                interactive=True, scale=1,
                            )
                            page_nav_next = gr.Button("Next >", size="sm", scale=1)

                        # Page context: shows which metrics reference current page (UX-1.2)
                        page_context_display = gr.HTML("")

                        # Citation carousel (UX-1.2)
                        citation_nav_display = gr.HTML("")
                        with gr.Row():
                            cite_prev_btn = gr.Button("< Prev Citation", size="sm", scale=1)
                            cite_next_btn = gr.Button("Next Citation >", size="sm", scale=1)

                        # Inline evidence panel
                        dashboard_evidence_html = gr.HTML("")

            # --- Tab 2: Batch Verification (HITL — UX-2.1, UX-2.2) ---
            with gr.Tab("Batch Verification"):
                # Confidence Dashboard (FR-4.5)
                confidence_dashboard_display = gr.HTML("")

                # Review Gate Banner (UX-2.1)
                review_gate_display = gr.HTML("")

                with gr.Row(equal_height=False):
                    # LEFT: Batch Review Table (UX-2.1)
                    with gr.Column(scale=3):
                        gr.Markdown("### Extraction Verification")
                        gr.Markdown(
                            "Review all extracted values below. "
                            "Click a row to see source evidence. "
                            "Edit values in the **Extracted Value** column "
                            "(editable fields: I/E Count, Endpoints, Visits, Invasive Procedures)."
                        )

                        # Bulk approve button (UX-2.1)
                        bulk_approve_btn = gr.Button(
                            "Bulk Approve High-Confidence Fields (\u2265 0.85)",
                            variant="secondary",
                            size="sm",
                        )

                        # Main batch review dataframe
                        verification_df = gr.Dataframe(
                            headers=[
                                "Field Name", "Extracted Value",
                                "Source Quote", "Page",
                                "Confidence", "Status",
                            ],
                            datatype=["str", "str", "str", "number", "number", "str"],
                            interactive=True,
                            wrap=True,
                            row_count=(1, "dynamic"),
                            col_count=(6, "fixed"),
                        )

                        # Action buttons
                        with gr.Row():
                            confirm_field_btn = gr.Button(
                                "Confirm Next Low-Confidence Field",
                                variant="secondary",
                                size="sm",
                                scale=1,
                            )
                            confirm_score_btn = gr.Button(
                                "Confirm & Score",
                                variant="primary",
                                size="lg",
                                scale=2,
                            )

                        # Audit log export (FR-4.4)
                        with gr.Row():
                            export_audit_btn = gr.Button(
                                "Export Audit Log (JSON)",
                                variant="secondary",
                                size="sm",
                            )
                            audit_download = gr.File(
                                label="Audit Log Download",
                                visible=False,
                            )

                    # RIGHT: Inline Source Evidence (UX-2.2)
                    with gr.Column(scale=2):
                        gr.Markdown("### Source Evidence")
                        inline_evidence_html = gr.HTML(
                            '<div style="color:#9CA3AF; padding:20px;">'
                            'Click a row in the table to see source evidence, '
                            'including the PDF page and AI reasoning.</div>'
                        )
                        evidence_thumbnail = gr.Image(
                            label="Source PDF Page",
                            type="pil",
                            height=400,
                        )

            # --- Tab 3: Optimization Simulator ---
            with gr.Tab("Optimization Simulator"):
                gr.Markdown("### What-If Analysis")
                gr.Markdown("Adjust protocol parameters to see the impact on complexity score.")
                with gr.Row():
                    with gr.Column():
                        sim_visits = gr.Slider(
                            minimum=1, maximum=50, value=18, step=1,
                            label="Total Visits",
                        )
                        sim_biopsies = gr.Slider(
                            minimum=0, maximum=10, value=3, step=1,
                            label="Invasive Procedures (Biopsies)",
                        )
                        sim_btn = gr.Button("Simulate", variant="secondary")
                    with gr.Column():
                        sim_result_html = gr.HTML("")
                        sim_chart = gr.Plot(label="Score Comparison")

                gr.Markdown("---")
                gr.Markdown("### Enrollment Timeline Calculator (FR-E6.4)")
                gr.Markdown("Estimate time to full enrollment based on projected rate.")
                with gr.Row():
                    with gr.Column():
                        enroll_sites = gr.Number(
                            label="Number of Sites", value=100,
                            minimum=1, interactive=True,
                        )
                        enroll_target = gr.Number(
                            label="Target Enrollment (N)", value=500,
                            minimum=1, interactive=True,
                        )
                        enroll_btn = gr.Button("Calculate Timeline", variant="secondary")
                    with gr.Column():
                        enroll_result_html = gr.HTML("")

            # --- Tab 4: AI Insights ---
            with gr.Tab("AI Insights"):
                insights_html = gr.HTML(
                    '<div style="color:#9CA3AF; padding:20px;">Select a protocol to see insights.</div>'
                )

        # =================================================================
        # EVENT WIRING
        # =================================================================

        # Mode toggle
        def toggle_mode(mode_val):
            is_upload = mode_val == "Upload Protocol"
            return (
                gr.update(visible=is_upload),
                gr.update(visible=not is_upload),
            )

        mode.change(
            toggle_mode, inputs=[mode],
            outputs=[upload_section, demo_section],
        )

        # LLM provider toggle — show Ollama status when selected
        def on_provider_change(provider):
            if provider == "Ollama (Local)":
                return gr.update(visible=True, value=get_ollama_status_html())
            return gr.update(visible=False, value="")

        llm_provider.change(
            on_provider_change, inputs=[llm_provider],
            outputs=[ollama_status],
        )

        # Demo selector change
        demo_selector.change(
            run_demo_analysis,
            inputs=[demo_selector],
            outputs=[scorecard_html, radar_chart, formula_html, insights_html, demo_info],
        )

        # Analyze button click — now outputs to batch verification tab too
        analyze_btn.click(
            run_extraction,
            inputs=[file_upload, llm_provider],
            outputs=[
                extraction_state, uploaded_file_state,
                scorecard_html, radar_chart,
                formula_html, pdf_page_display, error_display,
                # Batch verification outputs (UX-2.1)
                verification_state, verification_df,
                confidence_dashboard_display, review_gate_display,
                inline_evidence_html,
            ],
        ).then(
            # After extraction, populate the dashboard metric selector (UX-1.2)
            get_metric_choices,
            inputs=[extraction_state],
            outputs=[dashboard_metric_selector],
        )

        # --- Batch Verification Event Wiring (UX-2.1, UX-2.2, FR-4.4) ---

        # Row selection → inline evidence (UX-2.2)
        verification_df.select(
            on_batch_row_select,
            inputs=[extraction_state, uploaded_file_state],
            outputs=[inline_evidence_html, evidence_thumbnail],
        )

        # Cell edit → track changes & update audit log (FR-4.4)
        verification_df.change(
            on_batch_df_change,
            inputs=[verification_df, verification_state, extraction_state],
            outputs=[
                verification_df, verification_state,
                confidence_dashboard_display, review_gate_display,
            ],
        )

        # Confirm next low-confidence field
        confirm_field_btn.click(
            on_confirm_selected_field,
            inputs=[verification_df, verification_state, extraction_state],
            outputs=[
                verification_df, verification_state,
                confidence_dashboard_display, review_gate_display,
            ],
        )

        # Bulk approve high-confidence fields (UX-2.1)
        bulk_approve_btn.click(
            on_bulk_approve,
            inputs=[verification_df, verification_state, extraction_state],
            outputs=[
                verification_df, verification_state,
                confidence_dashboard_display, review_gate_display,
            ],
        )

        # Confirm & Score with review gate (UX-2.1 constraint)
        confirm_score_btn.click(
            on_confirm_and_score,
            inputs=[extraction_state, verification_state],
            outputs=[
                extraction_state, scorecard_html,
                radar_chart, formula_html, review_gate_display,
            ],
        )

        # Export audit log (FR-4.4)
        export_audit_btn.click(
            on_export_audit_log,
            inputs=[verification_state, extraction_state],
            outputs=[audit_download],
        )

        # PDF Export (UX-3.1, UX-3.2)
        export_pdf_btn.click(
            on_export_pdf,
            inputs=[extraction_state, verification_state, demo_selector, mode],
            outputs=[pdf_download],
        )

        # PDF page navigation (enhanced with page context — UX-1.2)
        page_nav_prev.click(
            lambda fb, p, rs: nav_page_with_context(fb, p, -1, rs),
            inputs=[uploaded_file_state, page_num_display, extraction_state],
            outputs=[pdf_page_display, page_num_display, page_context_display],
        )
        page_nav_next.click(
            lambda fb, p, rs: nav_page_with_context(fb, p, 1, rs),
            inputs=[uploaded_file_state, page_num_display, extraction_state],
            outputs=[pdf_page_display, page_num_display, page_context_display],
        )

        # Dashboard metric selector → jump to source (UX-1.2 Direction 1)
        dashboard_metric_selector.change(
            navigate_to_metric,
            inputs=[extraction_state, dashboard_metric_selector, uploaded_file_state],
            outputs=[
                pdf_page_display, page_num_display, page_context_display,
                citation_nav_display, dashboard_evidence_html, citation_index_state,
            ],
        )

        # Citation carousel prev/next (UX-1.2)
        cite_prev_btn.click(
            lambda rs, mk, ci, fb: cycle_citation(rs, mk, ci, -1, fb),
            inputs=[
                extraction_state, dashboard_metric_selector,
                citation_index_state, uploaded_file_state,
            ],
            outputs=[
                pdf_page_display, page_num_display, page_context_display,
                citation_nav_display, dashboard_evidence_html, citation_index_state,
            ],
        )
        cite_next_btn.click(
            lambda rs, mk, ci, fb: cycle_citation(rs, mk, ci, 1, fb),
            inputs=[
                extraction_state, dashboard_metric_selector,
                citation_index_state, uploaded_file_state,
            ],
            outputs=[
                pdf_page_display, page_num_display, page_context_display,
                citation_nav_display, dashboard_evidence_html, citation_index_state,
            ],
        )

        # Simulator
        sim_btn.click(
            run_simulator,
            inputs=[demo_selector, sim_visits, sim_biopsies, mode, extraction_state],
            outputs=[sim_result_html, sim_chart],
        )

        # Enrollment timeline calculator
        enroll_btn.click(
            run_enrollment_calculator,
            inputs=[enroll_sites, enroll_target, mode, extraction_state, demo_selector],
            outputs=[enroll_result_html],
        )

        # Load initial demo on startup
        app.load(
            run_demo_analysis,
            inputs=[demo_selector],
            outputs=[scorecard_html, radar_chart, formula_html, insights_html, demo_info],
        )

    return app


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = build_app()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        theme=gr.themes.Soft(),
        css=CUSTOM_CSS,
    )
