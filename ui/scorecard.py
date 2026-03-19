"""
Scorecard panel for ProtoScore V2 (left side of split-screen).

Renders the PCS score, 3 metric cards with confidence badges,
radar chart, and formula transparency display.

Design: Clinical Design System
"""

import gradio as gr
import plotly.graph_objects as go


def score_color(score: float) -> str:
    """Return color based on score severity."""
    if score < 30:
        return "#1A7A45"  # Green (low risk)
    elif score <= 60:
        return "#E68A00"  # Amber (moderate risk)
    return "#C0392B"      # Red (high risk)


def confidence_badge(confidence: float) -> str:
    """Return HTML badge for confidence level."""
    if confidence >= 0.80:
        color, label = "#1A7A45", "HIGH"
    elif confidence >= 0.60:
        color, label = "#E68A00", "MED"
    else:
        color, label = "#C0392B", "LOW"
    return (
        f'<span style="background:{color}; color:white; padding:2px 8px; '
        f'border-radius:10px; font-size:0.75em; font-weight:bold; '
        f"font-family:'Nunito Sans', sans-serif;\">"
        f'{label} ({confidence:.0%})</span>'
    )


def build_hero_metric(score: float) -> str:
    """Build the hero PCS score display."""
    color = score_color(score)
    return f"""
    <div style="text-align:center; padding:24px 20px; background:#0D1B2A;
                border-radius:12px; border-left:4px solid #0E7C86;
                min-height:120px; display:flex; flex-direction:column;
                justify-content:center; align-items:center;">
        <div style="font-size:13px; color:#94A3B8; text-transform:uppercase;
                    letter-spacing:0.08em; font-family:'Nunito Sans', sans-serif;">Protocol Complexity Score</div>
        <div style="font-size:56px; font-weight:700; color:#FFFFFF;
                    margin:10px 0; font-family:'Lora', Georgia, serif;">{score:.1f}</div>
        <div style="font-size:13px; color:#94A3B8;">/ 100</div>
    </div>
    """


def build_metric_card(
    title: str, score: float, detail: str,
    confidence: float = None, metric_key: str = ""
) -> str:
    """Build a single metric card with optional confidence badge."""
    color = score_color(score)
    conf_html = ""
    if confidence is not None:
        conf_html = f'<div style="margin-top:5px;">{confidence_badge(confidence)}</div>'

    return f"""
    <div style="background:#FFFFFF; padding:16px; border-radius:12px;
                border:1px solid #E2E8F0; border-left:3px solid {color};
                margin-bottom:12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <div style="display:flex; justify-content:space-between; align-items:start;">
            <div style="font-size:11px; color:#64748B; font-weight:600;
                        text-transform:uppercase; letter-spacing:0.08em;
                        font-family:'Nunito Sans', sans-serif;">{title}</div>
        </div>
        <div style="font-size:32px; font-weight:700; color:#0D1B2A;
                    margin:4px 0; font-family:'Lora', Georgia, serif;">{score:.1f}</div>
        <div style="font-size:13px; color:#64748B;">{detail}</div>
        {conf_html}
    </div>
    """


def build_radar_chart(breakdown: dict, protocol_name: str = "") -> go.Figure:
    """Build a radar/polar chart of the 3 complexity dimensions."""
    categories = list(breakdown.keys())
    values = list(breakdown.values())

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values,
        theta=categories,
        fill='toself',
        name=protocol_name,
        line_color='#0E7C86',
        fillcolor='rgba(14, 124, 134, 0.15)',
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], showticklabels=True,
                            gridcolor='#E2E8F0', color='#64748B'),
            angularaxis=dict(color='#334155'),
            bgcolor='rgba(0,0,0,0)',
        ),
        showlegend=False,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color="#334155", family="Nunito Sans"),
        margin=dict(l=60, r=60, t=30, b=30),
        height=350,
    )
    return fig


def build_formula_display(formula: dict) -> str:
    """Build the calculation transparency display (FR 4.3)."""
    return f"""
    <div style="background:#F0F4F8; padding:16px; border-radius:12px;
                border:1px solid #E2E8F0; margin-top:12px;">
        <div style="font-size:11px; color:#0E7C86; font-weight:600;
                    text-transform:uppercase; letter-spacing:0.08em;
                    margin-bottom:10px; font-family:'Nunito Sans', sans-serif;">SCORE FORMULA (Calculation Transparency)</div>
        <div style="font-family:'JetBrains Mono', 'Fira Code', monospace; font-size:12px; color:#334155; line-height:1.8;">
            <div><strong style="color:#0E7C86;">Complexity:</strong> {formula['complexity']}</div>
            <div><strong style="color:#E68A00;">Patient Burden:</strong> {formula['patient_burden']}</div>
            <div><strong style="color:#C0392B;">Site Burden:</strong> {formula['site_burden']}</div>
            <hr style="border-color:#E2E8F0; margin:8px 0;">
            <div><strong style="color:#0D1B2A;">Total PCS:</strong> {formula['total']}</div>
        </div>
    </div>
    """


def _tier_color(tier: str) -> str:
    """Return color for amendment risk tier."""
    tier_lower = tier.lower()
    if tier_lower == "low":
        return "#1A7A45"
    elif tier_lower == "moderate":
        return "#E68A00"
    return "#C0392B"


def build_amendment_risk_card(amendment_data: dict) -> str:
    """Build the Amendment Risk Score card (Pillar D)."""
    if not amendment_data:
        return ""

    score = amendment_data.get("score", 0)
    tier = amendment_data.get("tier", "Low")
    color = _tier_color(tier)
    findings = amendment_data.get("top_findings", [])
    rules_triggered = amendment_data.get("rules_triggered", 0)
    rules_evaluated = amendment_data.get("rules_evaluated", 0)

    findings_html = ""
    for f in findings:
        findings_html += f"""
        <li style="margin:6px 0;">
            <div style="background:#F0F4F8; padding:10px; border-radius:8px;
                        border-left:3px solid {_tier_color('high' if f.get('weight', 0) >= 0.7 else 'moderate' if f.get('weight', 0) >= 0.55 else 'low')};
                        font-size:13px;">
                <div style="color:#0D1B2A; font-weight:600;">{f.get('rule_id', '')} — {f.get('pattern', '')}</div>
                <div style="color:#64748B; margin-top:4px; font-style:italic;">
                    &ldquo;{f.get('matched_text', '')[:120]}&rdquo;
                    {f' · Page {f["page_number"]}' if f.get('page_number') else ''}
                </div>
                <div style="color:#0E7C86; margin-top:4px; font-size:12px;">
                    &#x2192; {f.get('mitigation', '')}
                </div>
            </div>
        </li>
        """

    findings_list = f'<ol style="margin:0; padding-left:20px; list-style-type:decimal; color:#64748B;">{findings_html}</ol>' if findings_html else '<div style="color:#94A3B8; font-size:13px;">No amendment risk patterns detected.</div>'

    return f"""
    <div style="background:#FFFFFF; padding:16px; border-radius:12px;
                border:1px solid {color}; margin-top:16px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <div>
                <div style="font-size:11px; color:#64748B; font-weight:600;
                            text-transform:uppercase; letter-spacing:0.08em;
                            font-family:'Nunito Sans', sans-serif;">Amendment Risk Score</div>
                <div style="font-size:12px; color:#94A3B8; margin-top:2px;">
                    {rules_triggered} of {rules_evaluated} patterns triggered
                </div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:32px; font-weight:700; color:#0D1B2A;
                            font-family:'Lora', Georgia, serif;">{score:.0f}</div>
                <span style="background:{color}; color:white; padding:4px 14px;
                             border-radius:20px; font-size:14px; font-weight:700;">
                    {tier} Risk
                </span>
            </div>
        </div>
        <div style="font-size:11px; color:#64748B; margin-bottom:8px; font-weight:600;
                    text-transform:uppercase; letter-spacing:0.08em;">
            TOP FINDINGS
        </div>
        {findings_list}
    </div>
    """


def build_amendment_formula_display(amendment_formula: dict) -> str:
    """Build the amendment risk formula transparency display."""
    if not amendment_formula:
        return ""

    formula = amendment_formula.get("formula", "")
    findings = amendment_formula.get("findings", [])
    score = amendment_formula.get("score", 0)
    tier = amendment_formula.get("tier", "Low")
    color = _tier_color(tier)

    findings_html = ""
    for f in findings:
        findings_html += f'<div style="margin-left:12px; color:#334155;">&#x2022; {f}</div>'

    return f"""
    <div style="background:#F0F4F8; padding:12px; border-radius:12px;
                border:1px solid #E2E8F0; margin-top:8px;">
        <div style="font-size:11px; color:{color}; font-weight:600; margin-bottom:8px;
                    text-transform:uppercase; letter-spacing:0.08em;
                    font-family:'Nunito Sans', sans-serif;">
            AMENDMENT RISK FORMULA (FR-D5.2)
        </div>
        <div style="font-family:'JetBrains Mono', 'Fira Code', monospace; font-size:12px; color:#334155; line-height:1.6;">
            <div>{formula}</div>
            {findings_html}
        </div>
    </div>
    """


def build_enrollment_card(enrollment_data: dict) -> str:
    """Build the Enrollment Rate Projection card (Pillar E)."""
    if not enrollment_data:
        return ""

    rate = enrollment_data.get("rate_per_site_per_month", 0)
    ci = enrollment_data.get("confidence_interval_80", [0, 0])
    refs = enrollment_data.get("reference_trials", [])
    restrictive = enrollment_data.get("top_restrictive_criteria", [])

    # Color and tier label based on enrollment rate (higher = better)
    if rate >= 2.0:
        rate_color, rate_tier = "#1A7A45", "Strong"
    elif rate >= 1.0:
        rate_color, rate_tier = "#E68A00", "Moderate"
    else:
        rate_color, rate_tier = "#C0392B", "Slow"

    # Reference trials
    refs_html = ""
    for ref in refs[:3]:
        refs_html += f"""
        <div style="display:flex; justify-content:space-between; padding:4px 0;
                    font-size:13px; border-bottom:1px solid #E2E8F0;">
            <span style="color:#0E7C86;">{ref.get('nct_id', '')}</span>
            <span style="color:#64748B;">{ref.get('tumor_type', '')} Ph{ref.get('phase', '')}</span>
            <span style="color:#0D1B2A;">{ref.get('enrollment_rate', 0)} pts/site/mo</span>
            <span style="color:#94A3B8;">sim: {ref.get('similarity', 0):.0%}</span>
        </div>
        """

    # Restrictive criteria
    restrict_html = ""
    for rc in restrictive:
        restrict_html += f"""
        <div style="background:#F0F4F8; padding:8px; border-radius:8px;
                    border-left:3px solid #E68A00; margin:4px 0; font-size:13px;">
            <span style="color:#0D1B2A; font-weight:600;">{rc.get('criterion', '')}</span>
            <span style="color:#1A7A45; float:right;">
                if relaxed: {rc.get('estimated_pool_impact', '')} eligible pool
            </span>
            <div style="color:#64748B; margin-top:2px; font-size:12px;">{rc.get('description', '')}</div>
        </div>
        """

    return f"""
    <div style="background:#FFFFFF; padding:16px; border-radius:12px;
                border:1px solid {rate_color}; margin-top:16px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <div>
                <div style="font-size:11px; color:#64748B; font-weight:600;
                            text-transform:uppercase; letter-spacing:0.08em;
                            font-family:'Nunito Sans', sans-serif;">Enrollment Rate Projection</div>
                <div style="font-size:12px; color:#94A3B8; margin-top:2px;">
                    Based on {len(refs)} similar completed trials
                </div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:32px; font-weight:700; color:#0D1B2A;
                            font-family:'Lora', Georgia, serif;">{rate}</div>
                <div style="font-size:12px; color:#64748B;">pts/site/month</div>
                <span style="background:{rate_color}; color:white; padding:4px 14px;
                             border-radius:20px; font-size:14px; font-weight:700;
                             display:inline-block; margin-top:4px;">
                    {rate_tier}
                </span>
                <div style="font-size:11px; color:#94A3B8; margin-top:4px;">
                    80% CI: [{ci[0]}, {ci[1]}]
                </div>
            </div>
        </div>

        <div style="font-size:11px; color:#64748B; margin-bottom:6px; font-weight:600;
                    text-transform:uppercase; letter-spacing:0.08em;">
            REFERENCE TRIALS
        </div>
        {refs_html if refs_html else '<div style="color:#94A3B8; font-size:13px;">No matching trials found.</div>'}

        {f"""
        <div style="font-size:11px; color:#64748B; margin-top:12px; margin-bottom:6px; font-weight:600;
                    text-transform:uppercase; letter-spacing:0.08em;">
            TOP RESTRICTIVE CRITERIA
        </div>
        {restrict_html}
        """ if restrict_html else ''}
    </div>
    """


def build_enrollment_formula_display(enrollment_data: dict) -> str:
    """Build enrollment projection formula transparency display."""
    if not enrollment_data:
        return ""

    rate = enrollment_data.get("rate_per_site_per_month", 0)
    ci = enrollment_data.get("confidence_interval_80", [0, 0])
    refs = enrollment_data.get("reference_trials", [])

    ref_strs = []
    for ref in refs[:3]:
        ref_strs.append(
            f"{ref.get('nct_id', '')} ({ref.get('tumor_type', '')} "
            f"Ph{ref.get('phase', '')}) = {ref.get('enrollment_rate', 0)} pts/site/mo "
            f"[sim: {ref.get('similarity', 0):.0%}]"
        )
    refs_html = "<br>".join(f"&nbsp;&nbsp;{s}" for s in ref_strs)

    return f"""
    <div style="background:#F0F4F8; padding:12px; border-radius:12px;
                border:1px solid #E2E8F0; margin-top:8px;">
        <div style="font-size:11px; color:#0E7C86; font-weight:600; margin-bottom:8px;
                    text-transform:uppercase; letter-spacing:0.08em;
                    font-family:'Nunito Sans', sans-serif;">
            ENROLLMENT PROJECTION (FR-E6.3)
        </div>
        <div style="font-family:'JetBrains Mono', 'Fira Code', monospace; font-size:12px; color:#334155; line-height:1.6;">
            <div>Rate = weighted k-NN average of top-5 similar trials</div>
            <div>= <strong>{rate}</strong> pts/site/month (80% CI: [{ci[0]}, {ci[1]}])</div>
            <div style="margin-top:6px;">Reference trials:</div>
            {refs_html}
        </div>
    </div>
    """


def build_burden_spikes_card(spikes: list) -> str:
    """Build the Burden Spikes warning card (FR-A1.5)."""
    if not spikes:
        return ""

    spike_rows = ""
    for s in spikes:
        reason_badge = {
            "both": "INVASIVE + TIME",
            "invasive_count": "INVASIVE",
            "time_threshold": "TIME",
        }.get(s.get("reason", ""), "BURDEN")

        procs_str = ", ".join(s.get("procedures", [])[:4])
        if len(s.get("procedures", [])) > 4:
            procs_str += f" (+{len(s['procedures']) - 4} more)"

        spike_rows += f"""
        <div style="background:#F0F4F8; padding:10px; border-radius:8px;
                    border-left:3px solid #C0392B; margin:6px 0; font-size:13px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="color:#0D1B2A; font-weight:600;">{s.get('visit_name', 'Unknown Visit')}</span>
                <span style="background:#C0392B; color:white; padding:2px 8px;
                             border-radius:8px; font-size:0.75em;">{reason_badge}</span>
            </div>
            <div style="color:#64748B; margin-top:4px;">
                {s.get('total_hours', 0)}h total &middot; {s.get('invasive_count', 0)} invasive procedures
            </div>
            <div style="color:#94A3B8; margin-top:2px; font-size:12px;">{procs_str}</div>
        </div>
        """

    return f"""
    <div style="background:#FFFFFF; padding:16px; border-radius:12px;
                border:1px solid #C0392B; margin-top:16px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <div style="font-size:11px; color:#C0392B; font-weight:600;
                    text-transform:uppercase; letter-spacing:0.08em; margin-bottom:8px;
                    font-family:'Nunito Sans', sans-serif;">
            Burden Spikes Detected ({len(spikes)} visit{'s' if len(spikes) != 1 else ''})
        </div>
        <div style="font-size:12px; color:#94A3B8; margin-bottom:10px;">
            Visits with &ge;3 invasive procedures or &ge;4 total hours (FR-A1.5)
        </div>
        {spike_rows}
    </div>
    """


def build_population_impact_card(impacts: list) -> str:
    """Build the Population Impact estimates card (FR-B2.5)."""
    if not impacts:
        return ""

    impact_rows = ""
    for p in impacts:
        pct = p.get("impact_pct", 0)
        if pct >= 50:
            bar_color = "#C0392B"
        elif pct >= 25:
            bar_color = "#E68A00"
        else:
            bar_color = "#1A7A45"

        suggestion_html = ""
        if p.get("suggestion"):
            suggestion_html = f'<div style="color:#0E7C86; margin-top:4px; font-size:12px;">&#x2192; {p["suggestion"]}</div>'

        impact_rows += f"""
        <div style="background:#F0F4F8; padding:10px; border-radius:8px;
                    border-left:3px solid {bar_color}; margin:6px 0; font-size:13px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="color:#0D1B2A; font-weight:600;">{p.get('criterion_text', '')[:80]}</span>
                <span style="color:{bar_color}; font-weight:700;">-{pct}%</span>
            </div>
            <div style="color:#64748B; margin-top:4px;">{p.get('description', '')}</div>
            <div style="background:#E2E8F0; border-radius:4px; height:6px; margin-top:6px; overflow:hidden;">
                <div style="background:{bar_color}; height:100%; width:{pct}%;"></div>
            </div>
            {suggestion_html}
        </div>
        """

    return f"""
    <div style="background:#FFFFFF; padding:16px; border-radius:12px;
                border:1px solid #E68A00; margin-top:16px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <div style="font-size:11px; color:#E68A00; font-weight:600;
                    text-transform:uppercase; letter-spacing:0.08em; margin-bottom:8px;
                    font-family:'Nunito Sans', sans-serif;">
            Population Impact Estimates ({len(impacts)} criteria)
        </div>
        <div style="font-size:12px; color:#94A3B8; margin-bottom:10px;">
            Estimated eligible-pool reduction per restrictive criterion (FR-B2.5)
        </div>
        {impact_rows}
    </div>
    """


def build_sequencing_risks_card(risks: list) -> str:
    """Build the Sequencing Risks warning card (FR-C3.3)."""
    if not risks:
        return ""

    risk_rows = ""
    for r in risks:
        risk_rows += f"""
        <div style="background:#F0F4F8; padding:10px; border-radius:8px;
                    border-left:3px solid #E68A00; margin:6px 0; font-size:13px;">
            <div style="color:#0D1B2A; font-weight:600;">
                {r.get('procedure_a', '')} &harr; {r.get('procedure_b', '')}
            </div>
            <div style="color:#E68A00; margin-top:4px;">
                {r.get('gap_days', 0)}-day gap &mdash; compounded invasive burden
            </div>
            <div style="color:#94A3B8; margin-top:2px; font-size:12px;">
                {r.get('risk_description', '')}
            </div>
        </div>
        """

    return f"""
    <div style="background:#FFFFFF; padding:16px; border-radius:12px;
                border:1px solid #E68A00; margin-top:16px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <div style="font-size:11px; color:#E68A00; font-weight:600;
                    text-transform:uppercase; letter-spacing:0.08em; margin-bottom:8px;
                    font-family:'Nunito Sans', sans-serif;">
            Sequencing Risks ({len(risks)} flagged)
        </div>
        <div style="font-size:12px; color:#94A3B8; margin-bottom:10px;">
            Invasive procedures within 14 days of each other (FR-C3.3)
        </div>
        {risk_rows}
    </div>
    """


def build_enhancement_formula_display(protocol_data: dict) -> str:
    """Build formula transparency for pillar enhancements."""
    parts = []

    pw = protocol_data.get("procedure_weight_summary", {})
    if pw:
        total_min = pw.get("total_patient_minutes", 0)
        mapped = pw.get("mapped_count", 0)
        coverage = pw.get("coverage_pct", 0)
        top_procs = pw.get("top_procedures", [])
        top_html = "".join(
            f"<div>&nbsp;&nbsp;{p['procedure']} ({p['category']}): {p['minutes']:.0f}min x{p['count']}</div>"
            for p in top_procs[:3]
        )
        parts.append(f"""
        <div style="margin-bottom:10px;">
            <div style="color:#0E7C86; font-weight:600;">PROCEDURE WEIGHTS (FR-A1.3)</div>
            <div>{mapped} procedures mapped ({coverage}% coverage)</div>
            <div>Total patient time: <strong>{total_min:.0f} minutes ({total_min / 60:.1f} hours)</strong></div>
            {top_html}
        </div>
        """)

    spikes = protocol_data.get("burden_spikes", [])
    if spikes:
        spike_strs = "; ".join(
            f"{s['visit_name']} ({s['total_hours']}h)" for s in spikes[:3]
        )
        parts.append(f"""
        <div style="margin-bottom:10px;">
            <div style="color:#C0392B; font-weight:600;">BURDEN SPIKES (FR-A1.5)</div>
            <div>{len(spikes)} visit(s) flagged: {spike_strs}</div>
        </div>
        """)

    impacts = protocol_data.get("population_impacts", [])
    if impacts:
        impact_strs = "; ".join(
            f"{p['impact_key']} (-{p['impact_pct']}%)" for p in impacts[:3]
        )
        parts.append(f"""
        <div style="margin-bottom:10px;">
            <div style="color:#E68A00; font-weight:600;">POPULATION IMPACT (FR-B2.5)</div>
            <div>{len(impacts)} restrictive criteria: {impact_strs}</div>
        </div>
        """)

    risks = protocol_data.get("sequencing_risks", [])
    if risks:
        risk_strs = "; ".join(
            f"{r['procedure_a']} + {r['procedure_b']} ({r['gap_days']}d)" for r in risks[:3]
        )
        parts.append(f"""
        <div style="margin-bottom:10px;">
            <div style="color:#E68A00; font-weight:600;">SEQUENCING RISKS (FR-C3.3)</div>
            <div>{len(risks)} risk(s): {risk_strs}</div>
        </div>
        """)

    if not parts:
        return ""

    return f"""
    <div style="background:#F0F4F8; padding:12px; border-radius:12px;
                border:1px solid #E2E8F0; margin-top:8px;">
        <div style="font-size:11px; color:#0E7C86; font-weight:600; margin-bottom:8px;
                    text-transform:uppercase; letter-spacing:0.08em;
                    font-family:'Nunito Sans', sans-serif;">
            ENHANCED PILLARS A/B/C
        </div>
        <div style="font-family:'JetBrains Mono', 'Fira Code', monospace; font-size:12px; color:#334155; line-height:1.6;">
            {"".join(parts)}
        </div>
    </div>
    """


def build_score_reliability_header(verif_state: dict | None) -> str:
    """
    Build the "Score Reliability" indicator for the scorecard header (FR-4.5).
    """
    if not verif_state:
        return ""

    from logic.audit_log import get_verification_stats
    stats = get_verification_stats(verif_state)

    total = stats["total"]
    if total == 0:
        return ""

    high_pct = stats["high_confidence_pct"]
    verified_pct = stats["verified_pct"]
    pending_pct = stats["pending_pct"]
    corrections = stats["corrections_count"]

    # Grade: A = all verified, B = >80%, C = >50%, D = <50%
    if verified_pct == 100:
        grade, grade_color = "A", "#1A7A45"
    elif verified_pct >= 80:
        grade, grade_color = "B", "#3A9CA5"
    elif verified_pct >= 50:
        grade, grade_color = "C", "#E68A00"
    else:
        grade, grade_color = "D", "#C0392B"

    verified_bar = min(verified_pct, 100)
    pending_bar = min(pending_pct, 100 - verified_bar)

    corrections_html = ""
    if corrections > 0:
        corrections_html = (
            f'<span style="color:#0E7C86;">{corrections} correction'
            f'{"s" if corrections != 1 else ""}</span>'
        )

    return f"""
    <div style="background:#FFFFFF; padding:10px 14px; border-radius:12px;
                border:1px solid {grade_color}; margin-bottom:12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-size:11px; color:#64748B; text-transform:uppercase;
                        letter-spacing:0.08em; font-weight:600;
                        font-family:'Nunito Sans', sans-serif;">Score Reliability</span>
            <span style="background:{grade_color}; color:white; padding:4px 12px;
                        border-radius:14px; font-size:14px; font-weight:800;
                        font-family:'Lora', Georgia, serif;">{grade}</span>
        </div>
        <div style="display:flex; height:6px; border-radius:3px; overflow:hidden;
                    margin:6px 0 4px 0; background:#E2E8F0;">
            <div style="width:{verified_bar}%; background:#1A7A45;"></div>
            <div style="width:{pending_bar}%; background:#E68A00;"></div>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:0.65em; color:#94A3B8;">
            <span style="color:#1A7A45;">Verified: {verified_pct}%</span>
            <span>High Conf: {high_pct}%</span>
            <span style="color:#E68A00;">Pending: {pending_pct}%</span>
            {corrections_html}
        </div>
    </div>
    """


def render_scorecard(score_result: dict, protocol_data: dict,
                     formula: dict = None, provenance: dict = None,
                     verif_state: dict = None) -> str:
    """
    Render the full scorecard as HTML.

    Args:
        score_result: Output from calculate_pcs()
        protocol_data: Protocol dict with metrics
        formula: Output from format_score_formula() (optional)
        provenance: Dict of ProvenanceRecord (optional, for analyst mode)
        verif_state: Verification state dict (optional, for FR-4.5 reliability header)

    Returns:
        Combined HTML string for the scorecard panel
    """
    html_parts = []

    # Hero metric
    html_parts.append(build_hero_metric(score_result['total']))

    # Score Reliability header (FR-4.5) — only in upload mode
    reliability_html = build_score_reliability_header(verif_state)
    if reliability_html:
        html_parts.append(reliability_html)

    # 3 metric cards
    ie_count = protocol_data['complexity_metrics']['ie_criteria_count']
    ep_count = protocol_data['complexity_metrics']['endpoints_count']
    visits = protocol_data['patient_burden']['total_visits']
    invasive = protocol_data['patient_burden']['invasive_procedures']
    staff_hrs = protocol_data['site_burden']['staff_hours_per_patient']

    # Get confidence scores if provenance is available
    c_conf = provenance.get("ie_criteria_count", None) if provenance else None
    c_conf_val = c_conf.confidence_score if c_conf else None
    p_conf = provenance.get("total_visits", None) if provenance else None
    p_conf_val = p_conf.confidence_score if p_conf else None

    html_parts.append('<div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; margin-top:12px;">')
    html_parts.append(build_metric_card(
        "Design Complexity", score_result['breakdown']['Complexity'],
        f"{ie_count} I/E Criteria  ·  {ep_count} Endpoints",
        confidence=c_conf_val, metric_key="complexity",
    ))
    html_parts.append(build_metric_card(
        "Patient Burden", score_result['breakdown']['Patient Burden'],
        f"{visits} Visits  ·  {invasive} Biopsies",
        confidence=p_conf_val, metric_key="patient",
    ))
    html_parts.append(build_metric_card(
        "Site Burden", score_result['breakdown']['Site Burden'],
        f"{staff_hrs} Staff Hrs/Pt",
        metric_key="site",
    ))
    html_parts.append('</div>')

    # Amendment Risk Score (Pillar D)
    amendment_data = protocol_data.get("amendment_risk")
    if amendment_data:
        html_parts.append(build_amendment_risk_card(amendment_data))

    # Enrollment Rate Projection (Pillar E)
    enrollment_data = protocol_data.get("enrollment_projection")
    if enrollment_data:
        html_parts.append(build_enrollment_card(enrollment_data))

    # Enhanced Pillars A/B/C
    burden_spikes = protocol_data.get("burden_spikes", [])
    if burden_spikes:
        html_parts.append(build_burden_spikes_card(burden_spikes))

    population_impacts = protocol_data.get("population_impacts", [])
    if population_impacts:
        html_parts.append(build_population_impact_card(population_impacts))

    sequencing_risks = protocol_data.get("sequencing_risks", [])
    if sequencing_risks:
        html_parts.append(build_sequencing_risks_card(sequencing_risks))

    # Formula transparency
    if formula:
        html_parts.append(build_formula_display(formula))

    return "\n".join(html_parts)
