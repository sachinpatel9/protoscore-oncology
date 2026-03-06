"""
Audit log and verification state management for HITL review (FR-4.4).

Records every human correction with field name, original value,
corrected value, timestamp, and user ID. Exportable as JSON
for regulatory submissions.

Verification state tracks per-field confirmation status and enforces
the review gate (UX-2.1): scoring is blocked until all fields with
confidence < 0.80 have been explicitly confirmed or corrected.
"""

import json
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Verification State Management
# ---------------------------------------------------------------------------

def init_verification_state(provenance: dict) -> dict:
    """
    Initialize verification state from ExtractionResult.provenance.

    Sets all fields to "pending", records original values and
    confidence scores for change detection and review gating.

    Args:
        provenance: Dict[str, ProvenanceRecord] from ExtractionResult

    Returns:
        Plain dict suitable for gr.State storage.
    """
    field_status = {}
    original_values = {}
    current_values = {}
    confidence_scores = {}
    metric_name_order = []

    for metric_name, record in provenance.items():
        # Skip sub-entries that roll up into parent metrics
        if metric_name.startswith("amendment_finding_"):
            continue

        field_status[metric_name] = "pending"
        original_values[metric_name] = record.value
        current_values[metric_name] = record.value
        confidence_scores[metric_name] = record.confidence_score
        metric_name_order.append(metric_name)

    return {
        "field_status": field_status,
        "original_values": original_values,
        "current_values": current_values,
        "confidence_scores": confidence_scores,
        "audit_entries": [],
        "metric_name_order": metric_name_order,
    }


# ---------------------------------------------------------------------------
# Audit Log Operations (append-only per FR-4.4 / DP-1.4)
# ---------------------------------------------------------------------------

def _make_audit_entry(
    field_name: str,
    original_value: Any,
    corrected_value: Any,
    action: str,
    confidence_before: float = 0.0,
    user_id: str = "reviewer",
) -> dict:
    """Create a single audit log entry dict."""
    return {
        "field_name": field_name,
        "original_value": original_value,
        "corrected_value": corrected_value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "action": action,
        "confidence_before": confidence_before,
    }


def record_correction(
    state_dict: dict,
    field_name: str,
    new_value: Any,
    user_id: str = "reviewer",
) -> dict:
    """
    Record a field value correction in the audit log.

    Updates field_status to "corrected", stores corrected value,
    and appends an audit entry.

    Args:
        state_dict: Current verification state
        field_name: Provenance metric name
        new_value: User-corrected value
        user_id: Identifier for the reviewer

    Returns:
        Updated state dict (mutated in place and returned).
    """
    original = state_dict["original_values"].get(field_name)
    confidence = state_dict["confidence_scores"].get(field_name, 0.0)

    state_dict["current_values"][field_name] = new_value
    state_dict["field_status"][field_name] = "corrected"

    entry = _make_audit_entry(
        field_name=field_name,
        original_value=original,
        corrected_value=new_value,
        action="corrected",
        confidence_before=confidence,
        user_id=user_id,
    )
    state_dict["audit_entries"].append(entry)

    return state_dict


def record_confirmation(
    state_dict: dict,
    field_name: str,
    user_id: str = "reviewer",
) -> dict:
    """
    Record that a field was explicitly confirmed without value change.

    Args:
        state_dict: Current verification state
        field_name: Provenance metric name
        user_id: Identifier for the reviewer

    Returns:
        Updated state dict.
    """
    current = state_dict["current_values"].get(field_name)
    confidence = state_dict["confidence_scores"].get(field_name, 0.0)

    state_dict["field_status"][field_name] = "confirmed"

    entry = _make_audit_entry(
        field_name=field_name,
        original_value=current,
        corrected_value=current,
        action="confirmed",
        confidence_before=confidence,
        user_id=user_id,
    )
    state_dict["audit_entries"].append(entry)

    return state_dict


def bulk_approve_high_confidence(
    state_dict: dict,
    threshold: float = 0.85,
    user_id: str = "reviewer",
) -> dict:
    """
    Bulk-approve all pending fields with confidence >= threshold.

    Creates an audit entry for each approved field.

    Args:
        state_dict: Current verification state
        threshold: Minimum confidence for auto-approval (default 0.85)
        user_id: Identifier for the reviewer

    Returns:
        Updated state dict.
    """
    for field_name, confidence in state_dict["confidence_scores"].items():
        if (
            confidence >= threshold
            and state_dict["field_status"].get(field_name) == "pending"
        ):
            current = state_dict["current_values"].get(field_name)
            state_dict["field_status"][field_name] = "bulk_approved"

            entry = _make_audit_entry(
                field_name=field_name,
                original_value=current,
                corrected_value=current,
                action="bulk_approved",
                confidence_before=confidence,
                user_id=user_id,
            )
            state_dict["audit_entries"].append(entry)

    return state_dict


# ---------------------------------------------------------------------------
# Review Gate (UX-2.1 constraint)
# ---------------------------------------------------------------------------

def get_review_gate_status(state_dict: dict) -> tuple[bool, str]:
    """
    Check if the review gate is satisfied.

    The gate requires that ALL fields with confidence < 0.80 have been
    explicitly confirmed or corrected before scoring can proceed.

    Returns:
        (is_satisfied, message) where message explains blocking fields.
    """
    if state_dict is None:
        return False, "No verification state available. Analyze a protocol first."

    blocking_fields = []
    for field_name, confidence in state_dict.get("confidence_scores", {}).items():
        if confidence < 0.80:
            status = state_dict.get("field_status", {}).get(field_name, "pending")
            if status == "pending":
                blocking_fields.append(field_name)

    if blocking_fields:
        field_list = ", ".join(blocking_fields)
        return (
            False,
            f"{len(blocking_fields)} low-confidence field(s) still need review: {field_list}",
        )

    return True, "All low-confidence fields have been reviewed. Ready to score."


# ---------------------------------------------------------------------------
# Statistics Helpers
# ---------------------------------------------------------------------------

def get_verification_stats(state_dict: dict) -> dict:
    """
    Compute verification statistics for the confidence dashboard (FR-4.5).

    Returns:
        Dict with keys: total, high_confidence, human_verified,
        pending, corrections_count, confirmations_count,
        high_confidence_pct, verified_pct, pending_pct.
    """
    if not state_dict:
        return {
            "total": 0, "high_confidence": 0, "human_verified": 0,
            "pending": 0, "corrections_count": 0, "confirmations_count": 0,
            "high_confidence_pct": 0, "verified_pct": 0, "pending_pct": 0,
        }

    statuses = state_dict.get("field_status", {})
    confidences = state_dict.get("confidence_scores", {})
    total = len(statuses)

    if total == 0:
        return {
            "total": 0, "high_confidence": 0, "human_verified": 0,
            "pending": 0, "corrections_count": 0, "confirmations_count": 0,
            "high_confidence_pct": 0, "verified_pct": 0, "pending_pct": 0,
        }

    high_confidence = sum(1 for c in confidences.values() if c >= 0.85)
    human_verified = sum(
        1 for s in statuses.values()
        if s in ("confirmed", "corrected", "bulk_approved")
    )
    pending = sum(1 for s in statuses.values() if s == "pending")

    corrections_count = sum(
        1 for e in state_dict.get("audit_entries", [])
        if e.get("action") == "corrected"
    )
    confirmations_count = sum(
        1 for e in state_dict.get("audit_entries", [])
        if e.get("action") in ("confirmed", "bulk_approved")
    )

    return {
        "total": total,
        "high_confidence": high_confidence,
        "human_verified": human_verified,
        "pending": pending,
        "corrections_count": corrections_count,
        "confirmations_count": confirmations_count,
        "high_confidence_pct": round(100 * high_confidence / total),
        "verified_pct": round(100 * human_verified / total),
        "pending_pct": round(100 * pending / total),
    }


# ---------------------------------------------------------------------------
# JSON Export (FR-4.4)
# ---------------------------------------------------------------------------

def export_audit_log_json(state_dict: dict, protocol_name: str = "") -> str:
    """
    Export the full audit log as formatted JSON for regulatory submissions.

    Includes metadata header with protocol name, export timestamp,
    field counts, and the complete audit entry list (append-only).

    Args:
        state_dict: Current verification state
        protocol_name: Source protocol filename

    Returns:
        Formatted JSON string.
    """
    if not state_dict:
        return json.dumps({"error": "No verification data available."}, indent=2)

    stats = get_verification_stats(state_dict)

    export = {
        "metadata": {
            "protocol_name": protocol_name,
            "export_timestamp": datetime.now(timezone.utc).isoformat(),
            "total_fields": stats["total"],
            "high_confidence_fields": stats["high_confidence"],
            "human_verified_fields": stats["human_verified"],
            "pending_fields": stats["pending"],
            "corrections_count": stats["corrections_count"],
            "confirmations_count": stats["confirmations_count"],
        },
        "field_summary": {
            field_name: {
                "status": state_dict["field_status"].get(field_name, "unknown"),
                "original_value": state_dict["original_values"].get(field_name),
                "current_value": state_dict["current_values"].get(field_name),
                "confidence": state_dict["confidence_scores"].get(field_name, 0),
            }
            for field_name in state_dict.get("metric_name_order", [])
        },
        "audit_trail": state_dict.get("audit_entries", []),
    }

    return json.dumps(export, indent=2, default=str)
