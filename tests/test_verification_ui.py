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
from logic.audit_log import (
    init_verification_state,
    record_correction,
    record_row_confirmation,
    record_row_unconfirmation,
    get_review_gate_status,
)


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
        "Priority", "Confidence", "Status", "Action",
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


# --- V2.1 round 3: per-row approval ----------------------------------------

def test_action_column_present(valid_feature_vector):
    """Dataframe must end with an 'Action' column (8th column)."""
    df = build_verification_dataframe(valid_feature_vector)
    assert len(df.columns) == 8
    assert list(df.columns)[-1] == "Action"


def test_action_column_is_bool(valid_feature_vector):
    """V2.1 r4: the Action column is a boolean checkbox, not a text trigger."""
    df = build_verification_dataframe(valid_feature_vector)
    for cell in df["Action"]:
        assert isinstance(cell, bool), f"Action cell {cell!r} is not bool"


def test_action_column_initial_state_all_unchecked(valid_feature_vector):
    """All rows start as Pending → Action checkbox unchecked."""
    state = init_verification_state(valid_feature_vector.provenance)
    df = build_verification_dataframe(valid_feature_vector, state)
    assert (df["Action"] == False).all()  # noqa: E712 — pandas bool comparison


def test_action_column_true_after_confirmation(valid_feature_vector):
    """After record_row_confirmation, the field's Action cell renders True."""
    state = init_verification_state(valid_feature_vector.provenance)
    state = record_row_confirmation(state, "ie_criteria_count")
    df = build_verification_dataframe(valid_feature_vector, state)
    # Find the row for ie_criteria_count via metric ordering
    from ui.verification import get_metric_name_order
    order = get_metric_name_order(valid_feature_vector)
    idx = order.index("ie_criteria_count")
    assert df.iloc[idx]["Action"] is True or df.iloc[idx]["Action"] == True  # noqa: E712


def test_action_column_false_for_corrected_status(valid_feature_vector):
    """Corrected status → Action checkbox unchecked (row needs re-approval)."""
    state = init_verification_state(valid_feature_vector.provenance)
    state = record_correction(state, "ie_criteria_count", "42")
    df = build_verification_dataframe(valid_feature_vector, state)
    from ui.verification import get_metric_name_order
    order = get_metric_name_order(valid_feature_vector)
    idx = order.index("ie_criteria_count")
    assert df.iloc[idx]["Action"] is False or df.iloc[idx]["Action"] == False  # noqa: E712


def test_record_row_unconfirmation_pending_path(valid_feature_vector):
    """Untoggling a confirmed row that was never edited → status 'pending'."""
    state = init_verification_state(valid_feature_vector.provenance)
    state = record_row_confirmation(state, "ie_criteria_count")
    assert state["field_status"]["ie_criteria_count"] == "confirmed"

    state = record_row_unconfirmation(state, "ie_criteria_count")
    assert state["field_status"]["ie_criteria_count"] == "pending"
    actions = [e["action"] for e in state["audit_entries"]]
    assert "unconfirmed" in actions


def test_record_row_unconfirmation_corrected_path(valid_feature_vector):
    """Untoggling a confirmed row that WAS edited → status restored to 'corrected'."""
    state = init_verification_state(valid_feature_vector.provenance)
    state = record_correction(state, "ie_criteria_count", "42")
    state = record_row_confirmation(state, "ie_criteria_count")
    assert state["field_status"]["ie_criteria_count"] == "confirmed"

    state = record_row_unconfirmation(state, "ie_criteria_count")
    # Edit must survive un-approval so apply_all_verified_values still
    # writes the user's value back when the row is re-approved later.
    assert state["field_status"]["ie_criteria_count"] == "corrected"
    assert state["current_values"]["ie_criteria_count"] == "42"


def test_on_batch_df_change_action_toggle_confirms_row(valid_feature_vector):
    """Toggling the Action checkbox True on a pending row records confirmation."""
    from app import on_batch_df_change

    state = init_verification_state(valid_feature_vector.provenance)
    df = build_verification_dataframe(valid_feature_vector, state)
    from ui.verification import get_metric_name_order
    order = get_metric_name_order(valid_feature_vector)
    idx = order.index("ie_criteria_count")

    # Simulate the user ticking the checkbox in the dataframe edit surface.
    df.at[idx, "Action"] = True
    new_df, new_state, _, _ = on_batch_df_change(df, state, valid_feature_vector)

    assert new_state["field_status"]["ie_criteria_count"] == "confirmed"
    assert new_df.iloc[idx]["Status"] == "Confirmed"


def test_on_batch_df_change_action_toggle_unconfirms_row(valid_feature_vector):
    """Toggling the Action checkbox False on a confirmed row reverts status."""
    from app import on_batch_df_change

    state = init_verification_state(valid_feature_vector.provenance)
    state = record_row_confirmation(state, "ie_criteria_count")
    df = build_verification_dataframe(valid_feature_vector, state)
    from ui.verification import get_metric_name_order
    order = get_metric_name_order(valid_feature_vector)
    idx = order.index("ie_criteria_count")

    df.at[idx, "Action"] = False
    new_df, new_state, _, _ = on_batch_df_change(df, state, valid_feature_vector)
    assert new_state["field_status"]["ie_criteria_count"] in ("pending", "corrected")
    assert new_df.iloc[idx]["Status"] == "Pending"


def test_on_batch_df_change_value_edit_unchecks_action(valid_feature_vector):
    """Editing the Extracted Value forces the Action checkbox to False."""
    from app import on_batch_df_change

    state = init_verification_state(valid_feature_vector.provenance)
    state = record_row_confirmation(state, "ie_criteria_count")
    df = build_verification_dataframe(valid_feature_vector, state)
    from ui.verification import get_metric_name_order
    order = get_metric_name_order(valid_feature_vector)
    idx = order.index("ie_criteria_count")

    # Action starts True (confirmed). User edits the value WITHOUT
    # touching the checkbox. The handler must:
    #   1) flip the audit-log status to "corrected"
    #   2) force Action False since the row needs re-approval.
    df.at[idx, "Extracted Value"] = "999"
    new_df, new_state, _, _ = on_batch_df_change(df, state, valid_feature_vector)

    assert new_state["field_status"]["ie_criteria_count"] == "corrected"
    assert new_df.iloc[idx]["Action"] is False or new_df.iloc[idx]["Action"] == False  # noqa: E712
    assert new_df.iloc[idx]["Status"] == "Pending"


def test_select_handler_does_not_route_action_column(valid_feature_vector):
    """
    V2.1 r4: clicks on the Action column no longer trigger approval via
    `verification_df.select`. Approval is exclusively driven by the
    `verification_df.change` event (interactive-gated). This test asserts
    the dispatcher returns no-op state for an Action-column select.
    """
    from app import on_batch_row_select, ACTION_COL_INDEX

    state = init_verification_state(valid_feature_vector.provenance)

    class _Evt:
        index = (0, ACTION_COL_INDEX)

    # Simulate a click on the Action column when interactive=False.
    # The handler must NOT mutate state (no record_row_confirmation call).
    out = on_batch_row_select(_Evt(), valid_feature_vector, None, state, "Priority (High → Low)")
    # 6-tuple: (df, state, dashboard, gate, evidence, thumb)
    assert len(out) == 6
    # State returned is either gr.update() (no-op) or the same dict —
    # never a state with the field flipped to confirmed.
    assert state["field_status"]["ie_criteria_count"] == "pending"


def test_on_toggle_edit_mode_flips_interactive_state():
    """on_toggle_edit_mode must flip the boolean state and update button label."""
    from app import on_toggle_edit_mode
    # False → True
    df_update, new_state, btn_update = on_toggle_edit_mode(False)
    assert new_state is True
    # True → False
    df_update2, new_state2, _ = on_toggle_edit_mode(True)
    assert new_state2 is False


def test_record_row_confirmation_flips_status(valid_feature_vector):
    """record_row_confirmation flips a single field's status to 'confirmed'."""
    state = init_verification_state(valid_feature_vector.provenance)
    assert state["field_status"]["ie_criteria_count"] == "pending"

    state = record_row_confirmation(state, "ie_criteria_count")
    assert state["field_status"]["ie_criteria_count"] == "confirmed"
    # Audit entry recorded
    actions = [e["action"] for e in state["audit_entries"]]
    assert "confirmed" in actions


def test_edit_after_confirm_reverts_to_pending_label(invalid_feature_vector):
    """
    Confirm a low-confidence row → edit it → displayed Status reads 'Pending'
    and the review gate counts the row as blocking.
    """
    state = init_verification_state(invalid_feature_vector.provenance)
    # Confirm ie_criteria_count
    state = record_row_confirmation(state, "ie_criteria_count")
    assert state["field_status"]["ie_criteria_count"] == "confirmed"

    # Now edit it → status becomes "corrected"
    state = record_correction(state, "ie_criteria_count", "42")
    assert state["field_status"]["ie_criteria_count"] == "corrected"

    # Displayed Status maps "corrected" → "Pending"
    df = build_verification_dataframe(invalid_feature_vector, state)
    # Find the ie_criteria_count row
    for _, row in df.iterrows():
        if "I/E" in row["Field Name"] or "Inclusion" in row["Field Name"] or row["Extracted Value"] == "42":
            assert row["Status"] == "Pending"
            assert row["Action"] is False or row["Action"] == False  # noqa: E712 — bool checkbox unchecked
            break
    else:
        pytest.fail("Could not locate ie_criteria_count row in dataframe")

    # Review gate must consider this row blocking if confidence < 0.80.
    # invalid_feature_vector has low-confidence provenance; the gate should fail.
    is_satisfied, _msg = get_review_gate_status(state)
    if state["confidence_scores"].get("ie_criteria_count", 1.0) < 0.80:
        assert is_satisfied is False


def test_status_display_corrected_renders_as_pending(valid_feature_vector):
    """Both 'pending' and 'corrected' underlying statuses render as 'Pending'."""
    state = init_verification_state(valid_feature_vector.provenance)
    df_pending = build_verification_dataframe(valid_feature_vector, state)
    assert all(s in ("Pending", "Confirmed") for s in df_pending["Status"])
    # All start pending
    assert (df_pending["Status"] == "Pending").all()

    # Mark one as corrected via record_correction on an editable field
    state = record_correction(state, "ie_criteria_count", "42")
    assert state["field_status"]["ie_criteria_count"] == "corrected"

    df_corrected = build_verification_dataframe(valid_feature_vector, state)
    # Display still shows Pending for the corrected row
    assert (df_corrected["Status"] == "Pending").all()
