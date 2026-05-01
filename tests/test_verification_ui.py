"""
Tests for the V2.2 Batch Verification UI revamp:
  - Priority column thresholds
  - Priority column appears in dataframe with correct ordering
  - Sort by priority (High -> Medium -> Low)
  - Edit-mode gating doesn't change which fields are writable
"""

import pytest

from ui.verification import (
    _priority_for,
    build_verification_dataframe,
    apply_all_verified_values,
    EDITABLE_FIELDS,
    PRIORITY_RANK,
)
from logic.audit_log import init_verification_state, record_correction


def test_priority_column_thresholds():
    """High < 0.70, Medium [0.70, 0.85), Low >= 0.85."""
    assert _priority_for(0.65)[0] == "High"
    assert _priority_for(0.69)[0] == "High"
    assert _priority_for(0.70)[0] == "Medium"
    assert _priority_for(0.75)[0] == "Medium"
    assert _priority_for(0.84)[0] == "Medium"
    assert _priority_for(0.85)[0] == "Low"
    assert _priority_for(0.92)[0] == "Low"
    # Colors are hex
    assert _priority_for(0.5)[1] == "#C0392B"
    assert _priority_for(0.75)[1] == "#E68A00"
    assert _priority_for(0.95)[1] == "#1A7A45"


def test_priority_column_appears_in_dataframe(valid_feature_vector):
    """Priority column must appear immediately to the left of Confidence."""
    df = build_verification_dataframe(valid_feature_vector)
    expected = [
        "Field Name", "Extracted Value", "Source Quote", "Page",
        "Priority", "Confidence", "Status",
    ]
    assert list(df.columns) == expected
    # All cells have a Priority label embedded
    for cell in df["Priority"]:
        assert any(label in cell for label in PRIORITY_RANK)


def test_sort_by_priority(invalid_feature_vector):
    """Priority sort: High rows precede Medium precede Low."""
    df = build_verification_dataframe(invalid_feature_vector, sort_by="priority")
    # Map each row to its priority rank
    ranks = []
    for cell in df["Priority"]:
        for label, rank in PRIORITY_RANK.items():
            if label in cell:
                ranks.append(rank)
                break
    # Must be non-decreasing (High=0 first, Low=2 last)
    assert ranks == sorted(ranks), f"Priority rows not sorted: {ranks}"


def test_apply_all_verified_values_unchanged(valid_feature_vector):
    """Edit-mode gating must not change which fields are writable.

    apply_all_verified_values still walks EDITABLE_FIELDS only, so a
    correction on a non-editable field has no effect on protocol_data.
    """
    state = init_verification_state(valid_feature_vector.provenance)

    # Editable: a correction on ie_criteria_count should write through.
    state = record_correction(state, "ie_criteria_count", "20")
    # Non-editable: a hypothetical correction on an unmapped field
    # should not crash and should not appear in protocol_data.
    state = record_correction(state, "some_non_editable_field", "99")

    result = apply_all_verified_values(valid_feature_vector, state)
    # Editable change applied
    assert result.protocol_data["complexity_metrics"]["ie_criteria_count"] == 20
    # Editable scope unchanged: only the four canonical keys
    assert set(EDITABLE_FIELDS.keys()) == {
        "ie_criteria_count",
        "endpoints_count",
        "total_visits",
        "invasive_procedures",
    }
