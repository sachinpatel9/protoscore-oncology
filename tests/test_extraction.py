"""
Unit tests for extraction validation:
- HITL review-flag thresholds on ProvenanceRecord
- SourceCitation required fields
- PII scrubber (email, phone, SSN)
- JSON feature-vector schema parity across OpenAI / Anthropic / Ollama providers
"""

import pytest
from unittest.mock import patch

from logic.ai_extractor import (
    ExtractionPipeline,
    OllamaExtractionPipeline,
    OpenAIExtractionPipeline,
    TOOL_SCHEMAS,
)
from logic.pii_scrubber import scrub_pii
from logic.provenance import ProvenanceRecord, SourceCitation, SourceType


# ---------------------------------------------------------------------------
# HITL review-flag thresholds (strict <, so 0.80 is NOT flagged)
# ---------------------------------------------------------------------------

def _record(confidence: float) -> ProvenanceRecord:
    return ProvenanceRecord(
        metric_name="test",
        value=10,
        display_label="Test",
        confidence_score=confidence,
    )


def test_low_confidence_triggers_review_flag():
    assert _record(0.65).needs_review is True


def test_high_confidence_does_not_trigger_review_flag():
    assert _record(0.85).needs_review is False


def test_confidence_just_below_threshold_triggers_review():
    assert _record(0.79).needs_review is True


def test_confidence_at_threshold_does_not_trigger_review():
    """Threshold is strictly <, so exactly 0.80 is NOT flagged for review."""
    assert _record(0.80).needs_review is False


def test_invalid_feature_vector_has_two_review_flags(invalid_feature_vector):
    flagged = [
        name for name, rec in invalid_feature_vector.provenance.items()
        if rec.needs_review
    ]
    assert len(flagged) == 2, f"expected 2 flagged records, got {flagged}"


def test_valid_feature_vector_has_no_review_flags(valid_feature_vector):
    flagged = [
        name for name, rec in valid_feature_vector.provenance.items()
        if rec.needs_review
    ]
    assert flagged == []


# ---------------------------------------------------------------------------
# SourceCitation contains the required source-metadata fields
# ---------------------------------------------------------------------------

def test_source_citation_has_required_fields():
    citation = SourceCitation(
        quote="Inclusion criteria: ECOG 0-1.",
        page_number=7,
        confidence_score=0.91,
        source_type=SourceType.TEXT,
    )
    assert citation.quote == "Inclusion criteria: ECOG 0-1."
    assert citation.page_number == 7
    assert citation.confidence_score == 0.91
    # All three are non-optional public attributes
    assert hasattr(citation, "quote")
    assert hasattr(citation, "page_number")
    assert hasattr(citation, "confidence_score")


# ---------------------------------------------------------------------------
# PII scrubber
# ---------------------------------------------------------------------------

def test_pii_scrubber_redacts_email():
    text = "Contact the PI at jane.doe@example.com for questions."
    scrubbed, records = scrub_pii(text)
    assert "[EMAIL_REDACTED]" in scrubbed
    assert "jane.doe@example.com" not in scrubbed
    assert any(r.pii_type == "email" for r in records)


@pytest.mark.parametrize("phone", [
    "555-123-4567",
    "(555) 123-4567",
    "+1-555-123-4567",
])
def test_pii_scrubber_redacts_phone_in_multiple_formats(phone):
    text = f"Call the study coordinator at {phone} during business hours."
    scrubbed, records = scrub_pii(text)
    assert "[PHONE_REDACTED]" in scrubbed, f"failed to redact format {phone!r}"
    assert phone not in scrubbed
    assert any(r.pii_type == "phone" for r in records)


def test_pii_scrubber_redacts_ssn():
    text = "Subject SSN 123-45-6789 was logged."
    scrubbed, records = scrub_pii(text)
    assert "[SSN_REDACTED]" in scrubbed
    assert "123-45-6789" not in scrubbed
    assert any(r.pii_type == "SSN" for r in records)


def test_pii_scrubber_returns_redaction_records():
    text = "Email: a@b.co  SSN: 111-22-3333"
    scrubbed, records = scrub_pii(text)
    types = {r.pii_type for r in records}
    assert {"email", "SSN"}.issubset(types)
    for r in records:
        assert r.original  # captured exact match
        assert r.redacted.startswith("[") and r.redacted.endswith("]")


def test_pii_scrubber_no_pii_passes_through_unchanged():
    text = "Eligible patients must have ECOG performance status of 0-1."
    scrubbed, records = scrub_pii(text)
    assert scrubbed == text
    assert records == []


# ---------------------------------------------------------------------------
# Schema parity across providers — the scoring engine MUST not be able to
# distinguish which provider produced an extraction.
# ---------------------------------------------------------------------------

REQUIRED_ENDPOINTS_KEYS = TOOL_SCHEMAS["extract_endpoints"]["required"]


def test_schema_consistency_anthropic(
    minimal_parsed_doc, mock_anthropic_client, mock_endpoints_payload,
):
    with patch("logic.ai_extractor.anthropic.Anthropic", return_value=mock_anthropic_client):
        pipeline = ExtractionPipeline(api_key="fake-key", parsed_doc=minimal_parsed_doc)
        result = pipeline._call_llm("extract endpoints from this", "extract_endpoints")

    assert isinstance(result, dict)
    for key in REQUIRED_ENDPOINTS_KEYS:
        assert key in result, f"Anthropic result missing required key: {key}"


def test_schema_consistency_openai(
    minimal_parsed_doc, mock_openai_client, mock_endpoints_payload,
):
    with patch("openai.OpenAI", return_value=mock_openai_client):
        pipeline = OpenAIExtractionPipeline(api_key="fake-key", parsed_doc=minimal_parsed_doc)
        result = pipeline._call_llm("extract endpoints from this", "extract_endpoints")

    assert isinstance(result, dict)
    for key in REQUIRED_ENDPOINTS_KEYS:
        assert key in result, f"OpenAI result missing required key: {key}"


def test_schema_consistency_ollama(minimal_parsed_doc, mock_endpoints_payload):
    with patch(
        "logic.ollama_utils.call_ollama_chat",
        return_value=mock_endpoints_payload,
    ):
        pipeline = OllamaExtractionPipeline(model="llama3.1:8b", parsed_doc=minimal_parsed_doc)
        result = pipeline._call_llm("extract endpoints from this", "extract_endpoints")

    assert isinstance(result, dict)
    for key in REQUIRED_ENDPOINTS_KEYS:
        assert key in result, f"Ollama result missing required key: {key}"


def test_schema_parity_across_all_three_providers(
    minimal_parsed_doc,
    mock_anthropic_client,
    mock_openai_client,
    mock_endpoints_payload,
):
    """All three providers must return dicts with the same key set for the same prompt."""
    with patch("logic.ai_extractor.anthropic.Anthropic", return_value=mock_anthropic_client):
        anth = ExtractionPipeline("fake", minimal_parsed_doc)._call_llm("p", "extract_endpoints")

    with patch("openai.OpenAI", return_value=mock_openai_client):
        oai = OpenAIExtractionPipeline("fake", minimal_parsed_doc)._call_llm("p", "extract_endpoints")

    with patch("logic.ollama_utils.call_ollama_chat", return_value=mock_endpoints_payload):
        oll = OllamaExtractionPipeline("llama3.1:8b", minimal_parsed_doc)._call_llm("p", "extract_endpoints")

    assert set(anth.keys()) == set(oai.keys()) == set(oll.keys()), (
        "Provider keys diverge: "
        f"anth={set(anth.keys())} openai={set(oai.keys())} ollama={set(oll.keys())}"
    )
