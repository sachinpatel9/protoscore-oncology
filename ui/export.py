"""
PDF Export module for ProtoScore V2 (UX-3.1, UX-3.2).

Generates a formatted PDF report containing:
- 1-page executive summary (sponsor-shareable, UX-3.2)
- Protocol Health Summary with per-pillar scores and formulas
- Amendment Risk findings
- Enrollment Rate projection
- Enhanced Pillar A/B/C findings
- Source citations index
- Optional verification audit summary

Uses fpdf2 for programmatic PDF generation.
Must complete export in < 10 seconds.

Design: Warm Clinical / Organic Modern (print palette)
"""

import io
import tempfile
from datetime import datetime, timezone

from fpdf import FPDF
from PIL import Image

from logic.audit_log import get_verification_stats


# ---------------------------------------------------------------------------
# Brand Constants (print-adapted warm palette)
# ---------------------------------------------------------------------------
SAGE = (91, 123, 111)        # #5B7B6F — primary accent
TERRACOTTA = (192, 117, 91)  # #C0755B — secondary accent / high risk
BRONZE = (139, 111, 78)      # #8B6F4E — tertiary accent
GOLD = (212, 160, 74)        # #D4A04A — warning/medium
DARK = (44, 44, 44)          # #2C2C2C — print text
GRAY = (107, 114, 128)       # #6B7280 — secondary text
LIGHT_GRAY = (229, 224, 216) # #E5E0D8 — borders/rules
WHITE = (255, 255, 255)
WARM_BG = (250, 247, 242)    # #FAF7F2 — tinted backgrounds

# Backward-compatible aliases
TEAL = SAGE
GREEN = SAGE
AMBER = GOLD
RED = TERRACOTTA

TIER_THRESHOLDS = [
    (30, "Low", SAGE),
    (55, "Moderate", GOLD),
    (75, "High", (220, 130, 50)),
    (100, "Very High", TERRACOTTA),
]


def get_complexity_tier(score: float) -> tuple[str, tuple[int, int, int]]:
    """Map PCS score to complexity tier label and color."""
    for threshold, label, color in TIER_THRESHOLDS:
        if score <= threshold:
            return label, color
    return "Very High", TERRACOTTA


def _score_color(score: float) -> tuple[int, int, int]:
    """Return RGB color based on score severity."""
    if score < 40:
        return SAGE
    elif score < 70:
        return GOLD
    return TERRACOTTA


def _render_plotly_to_image(fig, width=500, height=350):
    """Render a Plotly figure to a PIL Image for PDF embedding."""
    try:
        import plotly.graph_objects as go
        print_fig = go.Figure(fig.to_dict())
        print_fig.update_layout(
            paper_bgcolor="white",
            plot_bgcolor="white",
            font=dict(color="#2C2C2C", family="Nunito Sans"),
            polar=dict(
                radialaxis=dict(gridcolor="#E5E0D8", color="#2C2C2C"),
                angularaxis=dict(color="#2C2C2C"),
                bgcolor="white",
            ),
        )
        img_bytes = print_fig.to_image(
            format="png", width=width, height=height, engine="kaleido"
        )
        return Image.open(io.BytesIO(img_bytes))
    except Exception:
        return None


def _safe_text(text):
    """Strip non-latin-1 characters for fpdf2 built-in fonts."""
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ---------------------------------------------------------------------------
# Custom PDF Class
# ---------------------------------------------------------------------------

class ProtoScorePDF(FPDF):
    """FPDF subclass with ProtoScore branding for print reports."""

    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=20)
        self._generation_ts = datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )

    def header(self):
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*SAGE)
        self.cell(0, 6, "ProtoScore Oncology V2", align="L")
        self.set_text_color(*GRAY)
        self.set_font("Helvetica", "", 7)
        self.cell(0, 6, "CONFIDENTIAL", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*SAGE)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*GRAY)
        self.cell(0, 5, f"Generated {self._generation_ts}", align="L")
        self.cell(0, 5, f"Page {self.page_no()}/{{nb}}", align="R")

    def section_title(self, title, color=SAGE):
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(*color)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*color)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def subsection_title(self, title, color=DARK):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*color)
        self.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def body_text(self, text, bold=False):
        style = "B" if bold else ""
        self.set_font("Helvetica", style, 9)
        self.set_text_color(*DARK)
        self.multi_cell(0, 5, text)
        self.ln(1)

    def kpi_box(self, label, value, color=SAGE, w=55, h=22):
        """Render a KPI metric box with colored left accent bar."""
        x, y = self.get_x(), self.get_y()
        self.set_fill_color(*WARM_BG)
        self.rect(x, y, w, h, style="F")
        self.set_fill_color(*color)
        self.rect(x, y, 2.5, h, style="F")
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*GRAY)
        self.set_xy(x + 5, y + 2)
        self.cell(w - 7, 4, label)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*color)
        self.set_xy(x + 5, y + 7)
        self.cell(w - 7, 10, str(value))
        self.set_xy(x + w + 3, y)

    def data_table(self, headers, rows, col_widths=None):
        """Render a data table with header row and striped body."""
        available = 190
        if col_widths is None:
            col_widths = [available / len(headers)] * len(headers)

        # Header row
        self.set_font("Helvetica", "B", 8)
        self.set_fill_color(*SAGE)
        self.set_text_color(*WHITE)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, h, border=1, fill=True, align="C")
        self.ln()

        # Body rows
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*DARK)
        for row_idx, row in enumerate(rows):
            if row_idx % 2 == 0:
                self.set_fill_color(*WARM_BG)
            else:
                self.set_fill_color(*WHITE)
            for i, cell_text in enumerate(row):
                text = _safe_text(str(cell_text))
                max_chars = int(col_widths[i] * 0.55)
                if len(text) > max_chars:
                    text = text[: max_chars - 3] + "..."
                self.cell(
                    col_widths[i], 6, text, border=1, fill=True, align="L"
                )
            self.ln()

    def add_pil_image(self, img, x=None, w=0, h=0):
        """Add a PIL Image to the PDF."""
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(buf.read())
        tmp.close()
        if x is not None:
            self.image(tmp.name, x=x, w=w, h=h)
        else:
            self.image(tmp.name, w=w, h=h)


# ---------------------------------------------------------------------------
# Page Builders
# ---------------------------------------------------------------------------

def build_executive_summary_page(pdf, protocol_data, score_result,
                                  amendment_data=None, enrollment_data=None,
                                  verif_state=None):
    """Build the 1-page Executive Summary (UX-3.2 Sponsor Summary Page)."""
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*SAGE)
    pdf.cell(0, 10, "Executive Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Protocol identity
    name = _safe_text(protocol_data.get("name", "Unknown Protocol"))
    phase = protocol_data.get("phase", "")
    area = _safe_text(protocol_data.get("therapeutic_area", ""))
    design = _safe_text(protocol_data.get("study_design", ""))

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 6, name, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*GRAY)
    if phase:
        pdf.cell(
            0, 5, f"Phase {phase}  |  {area}",
            new_x="LMARGIN", new_y="NEXT",
        )
    if design:
        pdf.cell(0, 5, design, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # KPI row: PCS Score + Tier + Amendment Risk
    total = score_result["total"]
    tier, tier_color = get_complexity_tier(total)

    pdf.kpi_box(
        "Protocol Complexity Score", f"{total:.1f} / 100",
        color=_score_color(total), w=80, h=24,
    )
    pdf.kpi_box("Complexity Tier", tier, color=tier_color, w=55, h=24)
    if amendment_data:
        amr_score = amendment_data.get("score", 0)
        amr_tier = amendment_data.get("tier", "Low")
        pdf.kpi_box(
            "Amendment Risk", f"{amr_score:.0f} ({amr_tier})",
            color=_score_color(amr_score), w=55, h=24,
        )
    pdf.ln(28)

    # Pillar breakdown with bars
    breakdown = score_result.get("breakdown", {})
    if breakdown:
        pdf.subsection_title("Score Breakdown")
        for pillar, val in breakdown.items():
            color = _score_color(val)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*DARK)
            pdf.cell(50, 5, _safe_text(pillar))
            pdf.set_text_color(*color)
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(20, 5, f"{val:.1f}")
            bar_w = min(val, 100) * 0.8
            pdf.set_fill_color(*color)
            pdf.rect(pdf.get_x() + 2, pdf.get_y() + 1, bar_w, 3, style="F")
            pdf.set_fill_color(*LIGHT_GRAY)
            pdf.rect(
                pdf.get_x() + 2 + bar_w, pdf.get_y() + 1,
                80 - bar_w, 3, style="F",
            )
            pdf.ln(6)
        pdf.ln(2)

    # Score Reliability
    if verif_state:
        stats = get_verification_stats(verif_state)
        verified_pct = stats.get("verified_pct", 0)
        grade = (
            "A" if verified_pct == 100
            else "B" if verified_pct >= 80
            else "C" if verified_pct >= 50
            else "D"
        )
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*GRAY)
        pdf.cell(
            0, 5,
            f"Score Reliability: Grade {grade} ({verified_pct}% verified, "
            f"{stats.get('corrections_count', 0)} corrections)",
            new_x="LMARGIN", new_y="NEXT",
        )
        pdf.ln(2)

    # Top 5 Risk Findings
    pdf.subsection_title("Top Risk Findings", color=TERRACOTTA)
    risks = _aggregate_top_risks(protocol_data, amendment_data)
    if risks:
        for i, risk in enumerate(risks[:5], 1):
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(*DARK)
            pdf.cell(6, 5, f"{i}.")
            pdf.set_font("Helvetica", "", 8)
            pdf.multi_cell(0, 5, _safe_text(risk))
            pdf.ln(1)
    else:
        pdf.body_text("No significant risk findings identified.")
    pdf.ln(2)

    # Recommended Modifications
    pdf.subsection_title("Recommended Protocol Modifications", color=SAGE)
    mitigations = _get_top_mitigations(amendment_data)
    if mitigations:
        for i, m in enumerate(mitigations[:3], 1):
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(*DARK)
            pdf.cell(6, 5, f"{i}.")
            pdf.multi_cell(0, 5, _safe_text(m))
            pdf.ln(1)
    else:
        pdf.body_text("No modifications recommended at this complexity level.")

    # Enrollment summary
    if enrollment_data:
        rate = enrollment_data.get("rate_per_site_per_month", 0)
        ci = enrollment_data.get("confidence_interval_80", [0, 0])
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*GRAY)
        pdf.cell(
            0, 5,
            f"Enrollment Projection: {rate} pts/site/month "
            f"(80% CI: [{ci[0]}, {ci[1]}])",
            new_x="LMARGIN", new_y="NEXT",
        )


def build_health_summary_page(pdf, protocol_data, score_result, formula,
                               radar_fig=None):
    """Build the Protocol Health Summary page."""
    pdf.add_page()
    pdf.section_title("Protocol Health Summary")

    # Score breakdown table
    breakdown = score_result.get("breakdown", {})
    headers = ["Pillar", "Score", "Rating"]
    rows = []
    for pillar, val in breakdown.items():
        t, _ = get_complexity_tier(val)
        rows.append([pillar, f"{val:.1f}", t])
    rows.append([
        "TOTAL PCS", f"{score_result['total']:.1f}",
        get_complexity_tier(score_result["total"])[0],
    ])
    pdf.data_table(headers, rows, col_widths=[70, 30, 30])
    pdf.ln(6)

    # Radar chart
    if radar_fig is not None:
        chart_img = _render_plotly_to_image(radar_fig)
        if chart_img is not None:
            pdf.subsection_title("Multi-Dimensional Risk Profile")
            pdf.add_pil_image(chart_img, x=30, w=150)
            pdf.ln(4)

    # Formulas
    if formula:
        pdf.subsection_title("Score Formulas (Calculation Transparency)")
        pdf.set_font("Courier", "", 8)
        pdf.set_text_color(*DARK)
        for key, label in [
            ("complexity", "Complexity"),
            ("patient_burden", "Patient Burden"),
            ("site_burden", "Site Burden"),
            ("total", "Total PCS"),
        ]:
            if key in formula:
                text = formula[key].replace("**", "")
                pdf.set_font("Courier", "B", 8)
                pdf.cell(30, 5, f"{label}:")
                pdf.set_font("Courier", "", 8)
                pdf.multi_cell(0, 5, _safe_text(text))
                pdf.ln(1)


def build_amendment_risk_page(pdf, amendment_data):
    """Build the Amendment Risk Analysis page (Pillar D)."""
    if not amendment_data:
        return

    pdf.add_page()
    pdf.section_title("Amendment Risk Analysis (Pillar D)")

    score = amendment_data.get("score", 0)
    tier = amendment_data.get("tier", "Low")
    rules_triggered = amendment_data.get("rules_triggered", 0)
    rules_evaluated = amendment_data.get("rules_evaluated", 0)

    pdf.kpi_box(
        "Risk Score", f"{score:.0f} / 100",
        color=_score_color(score), w=60, h=22,
    )
    pdf.kpi_box("Risk Tier", tier, color=_score_color(score), w=45, h=22)
    pdf.kpi_box(
        "Patterns", f"{rules_triggered} / {rules_evaluated}",
        color=GRAY, w=45, h=22,
    )
    pdf.ln(26)

    findings = amendment_data.get("top_findings", [])
    if findings:
        pdf.subsection_title("Top Amendment Risk Findings")
        headers = ["Rule", "Pattern", "Matched Text", "Mitigation"]
        col_widths = [18, 45, 55, 72]
        rows = []
        for f in findings:
            rows.append([
                f.get("rule_id", ""),
                f.get("pattern", "")[:50],
                f.get("matched_text", "")[:60],
                f.get("mitigation", "")[:80],
            ])
        pdf.data_table(headers, rows, col_widths=col_widths)
    else:
        pdf.body_text("No amendment risk patterns detected.")

    pdf.ln(4)
    pdf.set_font("Courier", "", 8)
    pdf.set_text_color(*GRAY)
    pdf.cell(
        0, 5,
        f"Formula: Score = sum(weight x occurrences) x 100 / "
        f"max_possible = {score:.0f} [{tier}]",
        new_x="LMARGIN", new_y="NEXT",
    )


def build_enrollment_page(pdf, enrollment_data):
    """Build the Enrollment Projection page (Pillar E)."""
    if not enrollment_data:
        return

    pdf.add_page()
    pdf.section_title("Enrollment Rate Projection (Pillar E)")

    rate = enrollment_data.get("rate_per_site_per_month", 0)
    ci = enrollment_data.get("confidence_interval_80", [0, 0])
    refs = enrollment_data.get("reference_trials", [])
    restrictive = enrollment_data.get("top_restrictive_criteria", [])

    rate_color = SAGE if rate >= 2.0 else GOLD if rate >= 1.0 else TERRACOTTA
    pdf.kpi_box(
        "Enrollment Rate", f"{rate} pts/site/mo",
        color=rate_color, w=65, h=22,
    )
    pdf.kpi_box(
        "80% CI", f"[{ci[0]}, {ci[1]}]", color=GRAY, w=55, h=22,
    )
    pdf.kpi_box(
        "Reference Trials", str(len(refs)), color=SAGE, w=45, h=22,
    )
    pdf.ln(26)

    if refs:
        pdf.subsection_title("Reference Trials")
        headers = ["NCT ID", "Tumor Type", "Phase", "Rate", "Similarity"]
        col_widths = [35, 40, 20, 35, 30]
        rows = []
        for r in refs:
            rows.append([
                r.get("nct_id", ""),
                r.get("tumor_type", ""),
                r.get("phase", ""),
                f"{r.get('enrollment_rate', 0)} pts/site/mo",
                f"{r.get('similarity', 0):.0%}",
            ])
        pdf.data_table(headers, rows, col_widths=col_widths)
        pdf.ln(4)

    if restrictive:
        pdf.subsection_title("Top Restrictive Criteria")
        headers = ["Criterion", "Pool Impact", "Description"]
        col_widths = [55, 30, 105]
        rows = []
        for rc in restrictive:
            rows.append([
                rc.get("criterion", "")[:60],
                rc.get("estimated_pool_impact", ""),
                rc.get("description", "")[:100],
            ])
        pdf.data_table(headers, rows, col_widths=col_widths)


def build_detailed_findings_page(pdf, protocol_data):
    """Build the Detailed Findings page (Enhanced Pillars A/B/C)."""
    spikes = protocol_data.get("burden_spikes", [])
    impacts = protocol_data.get("population_impacts", [])
    risks = protocol_data.get("sequencing_risks", [])

    if not (spikes or impacts or risks):
        return

    pdf.add_page()
    pdf.section_title("Detailed Findings (Enhanced Pillars A/B/C)")

    if spikes:
        pdf.subsection_title(
            f"Burden Spikes ({len(spikes)} flagged visits)", color=TERRACOTTA,
        )
        headers = ["Visit", "Hours", "Invasive", "Procedures"]
        col_widths = [40, 20, 20, 110]
        rows = []
        for s in spikes:
            procs = ", ".join(s.get("procedures", [])[:5])
            rows.append([
                s.get("visit_name", ""),
                f"{s.get('total_hours', 0)}h",
                str(s.get("invasive_count", 0)),
                procs,
            ])
        pdf.data_table(headers, rows, col_widths=col_widths)
        pdf.ln(6)

    if impacts:
        pdf.subsection_title(
            f"Population Impact Estimates ({len(impacts)} criteria)",
            color=GOLD,
        )
        headers = ["Criterion", "Impact", "Suggestion"]
        col_widths = [60, 20, 110]
        rows = []
        for p in impacts:
            rows.append([
                p.get("criterion_text", "")[:65],
                f"-{p.get('impact_pct', 0)}%",
                (p.get("suggestion") or "N/A")[:100],
            ])
        pdf.data_table(headers, rows, col_widths=col_widths)
        pdf.ln(6)

    if risks:
        pdf.subsection_title(
            f"Sequencing Risks ({len(risks)} flagged)", color=GOLD,
        )
        headers = ["Procedure A", "Procedure B", "Gap (days)", "Risk"]
        col_widths = [40, 40, 25, 85]
        rows = []
        for r in risks:
            rows.append([
                r.get("procedure_a", ""),
                r.get("procedure_b", ""),
                str(r.get("gap_days", 0)),
                r.get("risk_description", "")[:90],
            ])
        pdf.data_table(headers, rows, col_widths=col_widths)


def build_citations_page(pdf, provenance=None, protocol_data=None):
    """Build the Source Citations Index page."""
    pdf.add_page()
    pdf.section_title("Source Citations Index")

    if provenance:
        headers = ["Metric", "Value", "Source Quote", "Page", "Conf."]
        col_widths = [35, 20, 85, 15, 15]
        rows = []
        for metric_name, record in provenance.items():
            if metric_name.startswith("amendment_finding_"):
                continue
            quote, page = "", ""
            if record.citations:
                cite = record.citations[0]
                quote = cite.quote[:90] if cite.quote else ""
                page = str(cite.page_number) if cite.page_number else ""
            rows.append([
                (record.display_label or metric_name)[:40],
                str(record.value)[:20],
                quote,
                page,
                f"{record.confidence_score:.0%}",
            ])
        if rows:
            pdf.data_table(headers, rows, col_widths=col_widths)
        else:
            pdf.body_text("No provenance records available.")
    else:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(*GRAY)
        pdf.multi_cell(
            0, 5,
            "Source citations are available when analyzing uploaded "
            "protocols. Demo protocols use pre-computed data without "
            "individual source citations.",
        )

    # Key metrics for demo mode
    if protocol_data and not provenance:
        pdf.ln(4)
        pdf.subsection_title("Key Extracted Metrics")
        cm = protocol_data.get("complexity_metrics", {})
        pb = protocol_data.get("patient_burden", {})
        sb = protocol_data.get("site_burden", {})
        headers = ["Metric", "Value"]
        col_widths = [90, 40]
        rows = [
            ["I/E Criteria Count", str(cm.get("ie_criteria_count", ""))],
            ["Endpoints Count", str(cm.get("endpoints_count", ""))],
            ["Total Visits", str(pb.get("total_visits", ""))],
            ["Invasive Procedures", str(pb.get("invasive_procedures", ""))],
            ["Staff Hours per Patient", str(sb.get("staff_hours_per_patient", ""))],
            ["Data Points per Visit", str(sb.get("data_points_per_visit", ""))],
        ]
        pdf.data_table(headers, rows, col_widths=col_widths)


def build_verification_page(pdf, verif_state, protocol_name=""):
    """Build the Verification Audit Summary page (upload mode only)."""
    if not verif_state:
        return

    pdf.add_page()
    pdf.section_title("Verification Audit Summary")

    stats = get_verification_stats(verif_state)
    total = stats.get("total", 0)
    if total == 0:
        pdf.body_text("No verification data available.")
        return

    verified_pct = stats.get("verified_pct", 0)
    if verified_pct == 100:
        grade, grade_color = "A", SAGE
    elif verified_pct >= 80:
        grade, grade_color = "B", (122, 158, 142)  # #7A9E8E
    elif verified_pct >= 50:
        grade, grade_color = "C", GOLD
    else:
        grade, grade_color = "D", TERRACOTTA

    pdf.kpi_box("Reliability Grade", grade, color=grade_color, w=50, h=24)
    pdf.kpi_box(
        "Fields Verified", f"{stats.get('human_verified', 0)} / {total}",
        color=SAGE, w=50, h=24,
    )
    pdf.kpi_box(
        "Corrections", str(stats.get("corrections_count", 0)),
        color=SAGE, w=45, h=24,
    )
    pdf.ln(28)

    pdf.subsection_title("Verification Statistics")
    headers = ["Metric", "Value"]
    col_widths = [90, 40]
    rows = [
        ["Total Fields", str(total)],
        [
            "High Confidence (>= 85%)",
            f"{stats.get('high_confidence', 0)} "
            f"({stats.get('high_confidence_pct', 0)}%)",
        ],
        ["Human Verified", f"{stats.get('human_verified', 0)} ({verified_pct}%)"],
        [
            "Pending Review",
            f"{stats.get('pending', 0)} ({stats.get('pending_pct', 0)}%)",
        ],
        ["Corrections", str(stats.get("corrections_count", 0))],
        ["Confirmations", str(stats.get("confirmations_count", 0))],
    ]
    pdf.data_table(headers, rows, col_widths=col_widths)

    corrections = [
        e for e in verif_state.get("audit_entries", [])
        if e.get("action") == "corrected"
    ]
    if corrections:
        pdf.ln(4)
        pdf.subsection_title("Corrections Made")
        headers = ["Field", "Original", "Corrected", "Timestamp"]
        col_widths = [45, 35, 35, 55]
        rows = []
        for c in corrections:
            rows.append([
                c.get("field_name", ""),
                str(c.get("original_value", "")),
                str(c.get("corrected_value", "")),
                c.get("timestamp", "")[:19],
            ])
        pdf.data_table(headers, rows, col_widths=col_widths)


# ---------------------------------------------------------------------------
# Risk Aggregation Helpers
# ---------------------------------------------------------------------------

def _aggregate_top_risks(protocol_data, amendment_data=None):
    """Aggregate top risk findings across all pillars for executive summary."""
    risks = []

    if amendment_data:
        for f in amendment_data.get("top_findings", []):
            weight = f.get("weight", 0)
            rule_id = f.get("rule_id", "")
            pattern = f.get("pattern", "")
            risks.append((weight, f"[{rule_id}] {pattern}"))

    for p in protocol_data.get("population_impacts", []):
        pct = p.get("impact_pct", 0)
        criterion = p.get("criterion_text", "")
        risks.append((pct / 100, f"Population impact: {criterion} (-{pct}%)"))

    for s in protocol_data.get("burden_spikes", []):
        visit = s.get("visit_name", "")
        hours = s.get("total_hours", 0)
        invasive = s.get("invasive_count", 0)
        risks.append((
            0.5,
            f"Burden spike at {visit}: {hours}h, {invasive} invasive procedures",
        ))

    for r in protocol_data.get("sequencing_risks", []):
        a = r.get("procedure_a", "")
        b = r.get("procedure_b", "")
        gap = r.get("gap_days", 0)
        risks.append((0.4, f"Sequencing risk: {a} + {b} within {gap} days"))

    risks.sort(key=lambda x: x[0], reverse=True)
    return [r[1] for r in risks]


def _get_top_mitigations(amendment_data):
    """Extract top mitigations from amendment risk findings."""
    if not amendment_data:
        return []
    return [
        f.get("mitigation", "")
        for f in amendment_data.get("top_findings", [])
        if f.get("mitigation")
    ]


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def generate_pdf_report(
    protocol_data,
    score_result,
    formula,
    radar_fig=None,
    provenance=None,
    verif_state=None,
    protocol_name="",
):
    """
    Generate the complete PDF report (UX-3.1, UX-3.2).

    Assembles all pages and writes to a temporary file.
    Must complete in < 10 seconds.

    Returns:
        Path to the generated temporary PDF file.
    """
    pdf = ProtoScorePDF()
    pdf.alias_nb_pages()

    amendment_data = protocol_data.get("amendment_risk")
    enrollment_data = protocol_data.get("enrollment_projection")

    # Page 1: Executive Summary (UX-3.2)
    build_executive_summary_page(
        pdf, protocol_data, score_result,
        amendment_data=amendment_data,
        enrollment_data=enrollment_data,
        verif_state=verif_state,
    )

    # Page 2: Protocol Health Summary
    build_health_summary_page(
        pdf, protocol_data, score_result, formula, radar_fig=radar_fig,
    )

    # Page 3: Amendment Risk (Pillar D)
    build_amendment_risk_page(pdf, amendment_data)

    # Page 4: Enrollment Projection (Pillar E)
    build_enrollment_page(pdf, enrollment_data)

    # Page 5: Detailed Findings (Enhanced A/B/C)
    build_detailed_findings_page(pdf, protocol_data)

    # Page 6: Source Citations Index
    build_citations_page(pdf, provenance=provenance, protocol_data=protocol_data)

    # Page 7: Verification Audit (optional)
    if verif_state:
        build_verification_page(pdf, verif_state, protocol_name=protocol_name)

    # Write to temp file
    tmp = tempfile.NamedTemporaryFile(
        suffix=".pdf", prefix="protoscore_report_", delete=False,
    )
    pdf.output(tmp.name)
    return tmp.name
