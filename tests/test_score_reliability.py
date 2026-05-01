"""
Tests for the redesigned Score Reliability panel (V2.1 round 2).

The panel uses three independent horizontal bars (Reliability Confidence,
Verified Extraction Values, Pending Confirmation Extracted Values) and no
longer renders a letter grade.
"""

from logic.audit_log import get_verification_stats, init_verification_state
from ui.verification import build_confidence_dashboard_html


def _verif_state_from_confidences(confidences: list[float]) -> dict:
    """Build a minimal verification state with the given confidence scores."""
    field_status = {}
    confidence_scores = {}
    original_values = {}
    current_values = {}
    metric_name_order = []
    for i, c in enumerate(confidences):
        name = f"field_{i}"
        field_status[name] = "pending"
        confidence_scores[name] = c
        original_values[name] = i
        current_values[name] = i
        metric_name_order.append(name)
    return {
        "field_status": field_status,
        "confidence_scores": confidence_scores,
        "original_values": original_values,
        "current_values": current_values,
        "audit_entries": [],
        "metric_name_order": metric_name_order,
    }


def test_mean_confidence_pct_calculation():
    state = _verif_state_from_confidences([0.9, 0.8, 0.7])
    stats = get_verification_stats(state)
    assert stats["mean_confidence_pct"] == 80


def test_no_letter_grade_in_html():
    state = _verif_state_from_confidences([0.9, 0.8, 0.7])
    html = build_confidence_dashboard_html(state)
    for forbidden in ("grade-A", "grade-B", "grade-C", "grade-D", 'class="grade-badge"'):
        assert forbidden not in html, f"forbidden token {forbidden!r} found in dashboard html"


def test_three_bar_labels_present():
    state = _verif_state_from_confidences([0.9, 0.8, 0.7])
    html = build_confidence_dashboard_html(state)
    assert "Reliability Confidence" in html
    assert "Verified Extraction" in html
    assert "Pending Confirmation" in html
