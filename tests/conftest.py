"""
Shared pytest fixtures for ProtoScore V2 tests.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Ensure repo root is on sys.path for `import logic.*` etc.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logic.data_manager import load_demo_data, get_protocol_details
from logic.pdf_parser import ParsedDocument, ParsedPage, TextBlock
from logic.provenance import (
    ExtractionResult,
    ProvenanceRecord,
    SourceCitation,
    SourceType,
)


# ---------------------------------------------------------------------------
# Demo protocol fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def demo_df():
    return load_demo_data()


@pytest.fixture
def demo_low(demo_df):
    return get_protocol_details(demo_df, "ONC-112-PhaseII")


@pytest.fixture
def demo_med(demo_df):
    return get_protocol_details(demo_df, "ONC-301-PhaseIII")


@pytest.fixture
def demo_high(demo_df):
    return get_protocol_details(demo_df, "HEM-045-PhaseI/II")


@pytest.fixture
def default_weights():
    return {"complexity": 0.4, "patient": 0.3, "site": 0.3}


# ---------------------------------------------------------------------------
# Feature vector fixtures (ExtractionResult with provenance)
# ---------------------------------------------------------------------------

def _make_record(name: str, value, confidence: float, label: str = "") -> ProvenanceRecord:
    citation = SourceCitation(
        quote="In total, 14 inclusion criteria were defined.",
        page_number=12,
        confidence_score=confidence,
        source_type=SourceType.TEXT,
    )
    return ProvenanceRecord(
        metric_name=name,
        value=value,
        display_label=label or name,
        confidence_score=confidence,
        citations=[citation],
        reasoning="explicitly stated in protocol text",
    )


@pytest.fixture
def valid_feature_vector():
    """ExtractionResult where every provenance record has confidence >= 0.85."""
    provenance = {
        "ie_criteria_count": _make_record("ie_criteria_count", 14, 0.95, "I/E Criteria"),
        "endpoints_count":   _make_record("endpoints_count",   5,  0.90, "Endpoints"),
        "total_visits":      _make_record("total_visits",      10, 0.88, "Total Visits"),
        "invasive_procedures": _make_record("invasive_procedures", 2, 0.92, "Invasive"),
    }
    return ExtractionResult(
        protocol_data={
            "complexity_metrics": {"ie_criteria_count": 14, "endpoints_count": 5},
            "patient_burden":     {"total_visits": 10, "invasive_procedures": 2},
            "site_burden":        {"staff_hours_per_patient": 60, "data_points_per_visit": 40},
        },
        provenance=provenance,
    )


@pytest.fixture
def invalid_feature_vector():
    """ExtractionResult with two records below the 0.80 review threshold."""
    provenance = {
        "ie_criteria_count": _make_record("ie_criteria_count", 14, 0.95, "I/E Criteria"),
        "endpoints_count":   _make_record("endpoints_count",   5,  0.65, "Endpoints"),    # low
        "total_visits":      _make_record("total_visits",      10, 0.88, "Total Visits"),
        "invasive_procedures": _make_record("invasive_procedures", 2, 0.45, "Invasive"),  # low
    }
    return ExtractionResult(
        protocol_data={
            "complexity_metrics": {"ie_criteria_count": 14, "endpoints_count": 5},
            "patient_burden":     {"total_visits": 10, "invasive_procedures": 2},
            "site_burden":        {"staff_hours_per_patient": 60, "data_points_per_visit": 40},
        },
        provenance=provenance,
    )


# ---------------------------------------------------------------------------
# Mock SDK response payloads & clients
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_endpoints_payload():
    """A canonical extract_endpoints response. Identical content for every provider."""
    return {
        "primary_endpoints": [
            {
                "name": "Overall response rate (ORR)",
                "description": "Per RECIST 1.1 at 24 weeks",
                "source_quote": "Primary endpoint: Overall response rate (ORR)",
                "page_number": 4,
            }
        ],
        "secondary_endpoints": [
            {
                "name": "Progression-free survival",
                "description": "Time from randomization to progression",
                "source_quote": "Secondary endpoint: PFS",
                "page_number": 4,
            }
        ],
        "exploratory_endpoints": [],
        "total_endpoints_count": 2,
        "confidence_score": 0.92,
        "reasoning": "Extracted from explicit endpoint section.",
    }


@pytest.fixture
def mock_anthropic_client(mock_endpoints_payload):
    """MagicMock shaped like anthropic.Anthropic for the tool_use response path."""
    client = MagicMock()
    block = SimpleNamespace(
        type="tool_use",
        name="extract_endpoints",
        input=mock_endpoints_payload,
    )
    response = SimpleNamespace(content=[block])
    client.messages.create.return_value = response
    return client


@pytest.fixture
def mock_openai_client(mock_endpoints_payload):
    """MagicMock shaped like openai.OpenAI for the chat.completions function-calling path."""
    client = MagicMock()
    tool_call = SimpleNamespace(
        function=SimpleNamespace(arguments=json.dumps(mock_endpoints_payload))
    )
    message = SimpleNamespace(tool_calls=[tool_call])
    choice = SimpleNamespace(message=message)
    response = SimpleNamespace(choices=[choice])
    client.chat.completions.create.return_value = response
    return client


# ---------------------------------------------------------------------------
# Minimal ParsedDocument for instantiating pipelines
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_parsed_doc():
    snippet = (
        "STUDY ENDPOINTS\n\n"
        "Primary endpoint: Overall response rate (ORR) at 24 weeks.\n"
        "Secondary endpoints: Progression-free survival.\n"
    )
    block = TextBlock(
        text=snippet,
        page_number=1,
        bbox=(0.0, 0.0, 100.0, 100.0),
        section_path=["Endpoints"],
    )
    page = ParsedPage(
        page_number=1,
        raw_text=snippet,
        text_blocks=[block],
        tables=[],
    )
    return ParsedDocument(
        pages=[page],
        section_hierarchy=[{"title": "Endpoints", "page_number": 1}],
        total_pages=1,
    )
