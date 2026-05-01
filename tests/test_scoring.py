"""
Unit tests for the deterministic PCS scoring engine.
"""

import pytest

from logic.scoring import calculate_pcs, format_score_formula


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_protocol(
    ie_criteria_count=0,
    endpoints_count=0,
    total_visits=0,
    invasive_procedures=0,
    staff_hours_per_patient=0,
    data_points_per_visit=0,
):
    """Build a minimal protocol dict containing only the fields scoring reads."""
    return {
        "complexity_metrics": {
            "ie_criteria_count": ie_criteria_count,
            "endpoints_count": endpoints_count,
        },
        "patient_burden": {
            "total_visits": total_visits,
            "invasive_procedures": invasive_procedures,
        },
        "site_burden": {
            "staff_hours_per_patient": staff_hours_per_patient,
            "data_points_per_visit": data_points_per_visit,
        },
    }


# ---------------------------------------------------------------------------
# Boundary conditions
# ---------------------------------------------------------------------------

def test_zero_input_returns_zero(default_weights):
    result = calculate_pcs(_make_protocol(), default_weights)
    assert result["total"] == 0.0
    assert result["breakdown"]["Complexity"] == 0.0
    assert result["breakdown"]["Patient Burden"] == 0.0
    assert result["breakdown"]["Site Burden"] == 0.0


def test_canonical_max_input_returns_100(default_weights):
    """All inputs at the design max → all sub-scores = 100, total = 100."""
    result = calculate_pcs(
        _make_protocol(
            ie_criteria_count=50, endpoints_count=20,
            total_visits=30, invasive_procedures=6,
            staff_hours_per_patient=200, data_points_per_visit=150,
        ),
        default_weights,
    )
    assert result["breakdown"]["Complexity"] == pytest.approx(100.0)
    assert result["breakdown"]["Patient Burden"] == pytest.approx(100.0)
    assert result["breakdown"]["Site Burden"] == pytest.approx(100.0)
    assert result["total"] == pytest.approx(100.0)


def test_zero_visits_contributes_zero_to_patient_burden(default_weights):
    """Patient burden has only the invasive contribution when visits=0."""
    result = calculate_pcs(
        _make_protocol(invasive_procedures=6),  # 6/6 * 0.6 * 100 = 60
        default_weights,
    )
    assert result["breakdown"]["Patient Burden"] == pytest.approx(60.0)


def test_zero_biopsies_contributes_zero_to_patient_burden(default_weights):
    """Patient burden has only the visits contribution when invasive=0."""
    result = calculate_pcs(
        _make_protocol(total_visits=30),  # 30/30 * 0.4 * 100 = 40
        default_weights,
    )
    assert result["breakdown"]["Patient Burden"] == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# Sub-score isolation
# ---------------------------------------------------------------------------

def test_complexity_subscore_isolated(default_weights):
    """Setting only complexity inputs should leave patient/site sub-scores at 0."""
    result = calculate_pcs(
        _make_protocol(ie_criteria_count=25, endpoints_count=10),
        default_weights,
    )
    # complexity = (25/50 * 0.5 + 10/20 * 0.5) * 100 = 50.0
    assert result["breakdown"]["Complexity"] == pytest.approx(50.0)
    assert result["breakdown"]["Patient Burden"] == 0.0
    assert result["breakdown"]["Site Burden"] == 0.0


def test_patient_burden_subscore_isolated(default_weights):
    result = calculate_pcs(
        _make_protocol(total_visits=15, invasive_procedures=3),
        default_weights,
    )
    # patient = (15/30 * 0.4 + 3/6 * 0.6) * 100 = 50.0
    assert result["breakdown"]["Patient Burden"] == pytest.approx(50.0)
    assert result["breakdown"]["Complexity"] == 0.0
    assert result["breakdown"]["Site Burden"] == 0.0


def test_site_burden_subscore_isolated(default_weights):
    result = calculate_pcs(
        _make_protocol(staff_hours_per_patient=100, data_points_per_visit=75),
        default_weights,
    )
    # site = (100/200 * 0.5 + 75/150 * 0.5) * 100 = 50.0
    assert result["breakdown"]["Site Burden"] == pytest.approx(50.0)
    assert result["breakdown"]["Complexity"] == 0.0
    assert result["breakdown"]["Patient Burden"] == 0.0


# ---------------------------------------------------------------------------
# Demo protocol ground truth
# ---------------------------------------------------------------------------

def test_demo_low_total_matches_ground_truth(demo_low, default_weights):
    """ONC-112-PhaseII (LOW) PCS calculated by hand: ~20.50."""
    result = calculate_pcs(demo_low, default_weights)
    assert result["total"] == pytest.approx(20.50, abs=0.05)


def test_demo_med_total_matches_ground_truth(demo_med, default_weights):
    """ONC-301-PhaseIII (MED) PCS calculated by hand: ~50.35."""
    result = calculate_pcs(demo_med, default_weights)
    assert result["total"] == pytest.approx(50.35, abs=0.05)


def test_demo_high_total_matches_ground_truth(demo_high, default_weights):
    """HEM-045-PhaseI/II (HIGH) PCS calculated by hand: ~91.90."""
    result = calculate_pcs(demo_high, default_weights)
    assert result["total"] == pytest.approx(91.90, abs=0.05)


def test_demo_low_breakdown_matches(demo_low, default_weights):
    result = calculate_pcs(demo_low, default_weights)
    assert result["breakdown"]["Complexity"] == pytest.approx(22.0, abs=0.05)
    assert result["breakdown"]["Patient Burden"] == pytest.approx(20.67, abs=0.05)
    assert result["breakdown"]["Site Burden"] == pytest.approx(18.33, abs=0.05)


def test_demo_med_breakdown_matches(demo_med, default_weights):
    result = calculate_pcs(demo_med, default_weights)
    assert result["breakdown"]["Complexity"] == pytest.approx(48.5, abs=0.05)
    assert result["breakdown"]["Patient Burden"] == pytest.approx(54.0, abs=0.05)
    assert result["breakdown"]["Site Burden"] == pytest.approx(49.17, abs=0.05)


def test_demo_high_breakdown_matches(demo_high, default_weights):
    """HIGH protocol's Patient Burden breakdown intentionally exceeds 100 (105.33).
    Scoring is unclamped by design — verify exact value, not a 0..100 bound."""
    result = calculate_pcs(demo_high, default_weights)
    assert result["breakdown"]["Complexity"] == pytest.approx(77.0, abs=0.05)
    assert result["breakdown"]["Patient Burden"] == pytest.approx(105.33, abs=0.05)
    assert result["breakdown"]["Site Burden"] == pytest.approx(98.33, abs=0.05)


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("protocol_id", ["ONC-112-PhaseII", "ONC-301-PhaseIII", "HEM-045-PhaseI/II"])
def test_demo_totals_in_zero_to_hundred_range(demo_df, default_weights, protocol_id):
    from logic.data_manager import get_protocol_details
    protocol = get_protocol_details(demo_df, protocol_id)
    result = calculate_pcs(protocol, default_weights)
    assert 0.0 <= result["total"] <= 100.0, (
        f"{protocol_id} total {result['total']} outside [0, 100]"
    )


# ---------------------------------------------------------------------------
# Formula transparency
# ---------------------------------------------------------------------------

def test_format_score_formula_returns_expected_keys(demo_med, default_weights):
    formula = format_score_formula(demo_med, default_weights)
    assert {"complexity", "patient_burden", "site_burden", "total", "values"}.issubset(formula.keys())
    assert isinstance(formula["complexity"], str)
    assert isinstance(formula["values"], dict)
    # The numeric values dict mirrors the breakdown
    assert formula["values"]["complexity"] == pytest.approx(48.5, abs=0.05)
    assert formula["values"]["total"] == pytest.approx(50.35, abs=0.05)
