"""
Protocol Complexity Score (PCS) calculation engine for ProtoScore.

The scoring algorithm is DETERMINISTIC — the LLM fills the JSON feature
vector, but this Python code calculates the actual score. This is the
"Safety Valve" ensuring no hallucinated scores.
"""

import numpy as np


def calculate_pcs(protocol_data, weights):
    """
    Calculate the Protocol Complexity Score (PCS) based on dynamic weights.
    weights: dict -> {'complexity': 0.4, 'patient': 0.3, 'site': 0.3}
    """
    # 1. Normalize complexity features
    # Static max values for normalization (production would use dynamic thresholds)
    c_score = (
        (protocol_data['complexity_metrics']['ie_criteria_count'] / 50) * 0.5 +
        (protocol_data['complexity_metrics']['endpoints_count'] / 20) * 0.5) * 100

    # 2. Normalize Patient Burden features
    p_score = (
        (protocol_data['patient_burden']['total_visits'] / 30) * 0.4 +
        (protocol_data['patient_burden']['invasive_procedures'] / 6) * 0.6) * 100

    # 3. Normalize Site Burden features
    s_score = (
            (protocol_data['site_burden']['staff_hours_per_patient'] / 200) * 0.5 +
            (protocol_data['site_burden']['data_points_per_visit'] / 150) * 0.5
        ) * 100

    # 4. Weighted sum to get final PCS
    final_score = (
        (c_score * weights['complexity']) +
        (p_score * weights['patient']) +
        (s_score * weights['site'])
    )
    return {
        "total": round(final_score, 2),
        "breakdown": {
            "Complexity": round(c_score, 2),
            "Patient Burden": round(p_score, 2),
            "Site Burden": round(s_score, 2)
        }
    }


def format_score_formula(protocol_data, weights) -> dict:
    """
    Generate a transparent formula display showing the calculation with
    plugged-in values. Satisfies FR 4.3 (Calculation Transparency).

    Returns:
        Dict with 'complexity', 'patient_burden', 'site_burden', and
        'total' formula strings.
    """
    ie = protocol_data['complexity_metrics']['ie_criteria_count']
    ep = protocol_data['complexity_metrics']['endpoints_count']
    visits = protocol_data['patient_burden']['total_visits']
    invasive = protocol_data['patient_burden']['invasive_procedures']
    staff_hrs = protocol_data['site_burden']['staff_hours_per_patient']
    data_pts = protocol_data['site_burden']['data_points_per_visit']

    wc = weights['complexity']
    wp = weights['patient']
    ws = weights['site']

    c_score = ((ie / 50) * 0.5 + (ep / 20) * 0.5) * 100
    p_score = ((visits / 30) * 0.4 + (invasive / 6) * 0.6) * 100
    s_score = ((staff_hrs / 200) * 0.5 + (data_pts / 150) * 0.5) * 100
    total = c_score * wc + p_score * wp + s_score * ws

    return {
        "complexity": (
            f"(I/E [{ie}] / 50 × 0.5  +  Endpoints [{ep}] / 20 × 0.5) × 100"
            f"  =  {c_score:.1f}"
        ),
        "patient_burden": (
            f"(Visits [{visits}] / 30 × 0.4  +  Biopsies [{invasive}] / 6 × 0.6) × 100"
            f"  =  {p_score:.1f}"
        ),
        "site_burden": (
            f"(Staff Hrs [{staff_hrs}] / 200 × 0.5  +  Data Pts [{data_pts}] / 150 × 0.5) × 100"
            f"  =  {s_score:.1f}"
        ),
        "total": (
            f"Complexity [{c_score:.1f}] × {wc}  +  "
            f"Patient [{p_score:.1f}] × {wp}  +  "
            f"Site [{s_score:.1f}] × {ws}"
            f"  =  **{total:.1f}**"
        ),
        "values": {
            "complexity": round(c_score, 2),
            "patient_burden": round(p_score, 2),
            "site_burden": round(s_score, 2),
            "total": round(total, 2),
        },
    }


def format_amendment_risk_formula(amendment_data: dict) -> dict:
    """
    Generate a transparent formula display for the Amendment Risk Score (FR-D5.2).

    Args:
        amendment_data: Dict with 'score', 'tier', 'top_findings' from evaluation

    Returns:
        Dict with 'formula', 'findings', 'score', 'tier' for display
    """
    if not amendment_data:
        return {}

    score = amendment_data.get("score", 0)
    tier = amendment_data.get("tier", "Low")
    findings = amendment_data.get("top_findings", [])

    finding_strs = []
    for f in findings:
        rule_id = f.get("rule_id", "")
        weight = f.get("weight", 0)
        occurrences = f.get("occurrences", 1)
        pattern = f.get("pattern", "")
        finding_strs.append(
            f"{rule_id}: {pattern} (weight={weight} x {occurrences} occurrence{'s' if occurrences != 1 else ''})"
        )

    formula = (
        f"Score = sum(weight x occurrences) x 100 / max_possible  =  {score:.0f}  [{tier}]"
    )

    return {
        "formula": formula,
        "findings": finding_strs,
        "score": score,
        "tier": tier,
    }
