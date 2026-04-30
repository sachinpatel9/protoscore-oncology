"""
Provider-agnostic extraction pipeline base class for ProtoScore V2.

Defines:
- The five Anthropic-style tool schemas used by every provider as the source of
  truth for the JSON feature vector (`TOOL_SCHEMAS`, plus full Anthropic-shaped
  defs in `_TOOL_BY_NAME` for OpenAI's function description field).
- `BaseExtractionPipeline`: the 3-agent orchestration (Logic, Table, Temporal)
  plus endpoints + amendment risk + enrollment projection + pillar enhancements.

Concrete providers live in sibling files (`anthropic.py`, `openai.py`,
`ollama.py`) and only need to implement `_call_llm()` and `model_name`.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Callable, Optional

from logic.pdf_parser import ParsedDocument
from logic.prompts import (
    TABLE_AGENT_PROMPT,
    LOGIC_AGENT_PROMPT,
    TEMPORAL_AGENT_PROMPT,
    ENDPOINTS_PROMPT,
    build_router_prompt,
    build_extraction_prompt,
)
from logic.provenance import (
    ExtractionResult,
    ProvenanceRecord,
    SourceCitation,
    SourceType,
)
from logic.amendment_engine import evaluate_amendment_risk, build_amendment_provenance
from logic.enrollment_projector import project_enrollment, build_enrollment_provenance
from logic.pillar_enhancements import run_pillar_enhancements, build_enhancement_provenance

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool schemas — single source of truth, reused across all providers
# ---------------------------------------------------------------------------

EXTRACT_IE_CRITERIA_TOOL = {
    "name": "extract_ie_criteria",
    "description": "Extract inclusion and exclusion criteria from the protocol.",
    "input_schema": {
        "type": "object",
        "properties": {
            "inclusion_criteria": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "criterion_number": {"type": "integer"},
                        "text": {"type": "string"},
                        "source_quote": {"type": "string"},
                        "page_number": {"type": "integer"},
                        "is_conditional": {"type": "boolean"},
                        "condition_text": {"type": "string"},
                    },
                    "required": ["criterion_number", "text", "source_quote", "page_number"],
                },
            },
            "exclusion_criteria": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "criterion_number": {"type": "integer"},
                        "text": {"type": "string"},
                        "source_quote": {"type": "string"},
                        "page_number": {"type": "integer"},
                        "is_conditional": {"type": "boolean"},
                        "condition_text": {"type": "string"},
                        "restrictiveness": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                        "reasoning": {"type": "string"},
                    },
                    "required": ["criterion_number", "text", "source_quote", "page_number"],
                },
            },
            "total_ie_count": {"type": "integer"},
            "confidence_score": {"type": "number", "minimum": 0, "maximum": 1},
            "reasoning": {"type": "string"},
        },
        "required": ["inclusion_criteria", "exclusion_criteria", "total_ie_count", "confidence_score"],
    },
}


EXTRACT_VISIT_SCHEDULE_TOOL = {
    "name": "extract_visit_schedule",
    "description": "Extract the Schedule of Assessments table and visit information.",
    "input_schema": {
        "type": "object",
        "properties": {
            "schedule_table": {
                "type": "object",
                "description": "Flattened SoA: keys are procedure names, values are dicts of visit->mark",
                "additionalProperties": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
            },
            "total_visits": {"type": "integer"},
            "study_duration_weeks": {"type": "integer"},
            "visit_names": {
                "type": "array",
                "items": {"type": "string"},
            },
            "source_page_numbers": {
                "type": "array",
                "items": {"type": "integer"},
            },
            "source_quote": {"type": "string"},
            "confidence_score": {"type": "number", "minimum": 0, "maximum": 1},
            "reasoning": {"type": "string"},
        },
        "required": ["total_visits", "confidence_score"],
    },
}


EXTRACT_PROCEDURES_TOOL = {
    "name": "extract_procedures",
    "description": "Extract invasive procedures and map them to the trial timeline.",
    "input_schema": {
        "type": "object",
        "properties": {
            "invasive_procedures": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "procedure_name": {"type": "string"},
                        "count": {"type": "integer"},
                        "study_phase": {
                            "type": "string",
                            "enum": ["screening", "treatment", "follow_up"],
                        },
                        "timing": {"type": "string"},
                        "source_quote": {"type": "string"},
                        "page_number": {"type": "integer"},
                    },
                    "required": ["procedure_name", "count", "source_quote", "page_number"],
                },
            },
            "burden_spikes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "visit_name": {"type": "string"},
                        "estimated_hours": {"type": "number"},
                        "procedures_in_visit": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            },
            "total_invasive_count": {"type": "integer"},
            "confidence_score": {"type": "number", "minimum": 0, "maximum": 1},
            "reasoning": {"type": "string"},
        },
        "required": ["invasive_procedures", "total_invasive_count", "confidence_score"],
    },
}


EXTRACT_ENDPOINTS_TOOL = {
    "name": "extract_endpoints",
    "description": "Extract primary, secondary, and exploratory endpoints.",
    "input_schema": {
        "type": "object",
        "properties": {
            "primary_endpoints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "source_quote": {"type": "string"},
                        "page_number": {"type": "integer"},
                    },
                    "required": ["name", "source_quote", "page_number"],
                },
            },
            "secondary_endpoints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "source_quote": {"type": "string"},
                        "page_number": {"type": "integer"},
                    },
                    "required": ["name", "source_quote", "page_number"],
                },
            },
            "exploratory_endpoints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "source_quote": {"type": "string"},
                        "page_number": {"type": "integer"},
                    },
                },
            },
            "total_endpoints_count": {"type": "integer"},
            "confidence_score": {"type": "number", "minimum": 0, "maximum": 1},
            "reasoning": {"type": "string"},
        },
        "required": ["primary_endpoints", "secondary_endpoints", "total_endpoints_count", "confidence_score"],
    },
}


CLASSIFY_SECTIONS_TOOL = {
    "name": "classify_sections",
    "description": "Map protocol sections to extraction categories.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ie_criteria": {
                "type": "object",
                "properties": {
                    "section_titles": {"type": "array", "items": {"type": "string"}},
                    "page_numbers": {"type": "array", "items": {"type": "integer"}},
                },
            },
            "endpoints": {
                "type": "object",
                "properties": {
                    "section_titles": {"type": "array", "items": {"type": "string"}},
                    "page_numbers": {"type": "array", "items": {"type": "integer"}},
                },
            },
            "schedule": {
                "type": "object",
                "properties": {
                    "section_titles": {"type": "array", "items": {"type": "string"}},
                    "page_numbers": {"type": "array", "items": {"type": "integer"}},
                },
            },
            "procedures": {
                "type": "object",
                "properties": {
                    "section_titles": {"type": "array", "items": {"type": "string"}},
                    "page_numbers": {"type": "array", "items": {"type": "integer"}},
                },
            },
        },
        "required": ["ie_criteria", "endpoints", "schedule", "procedures"],
    },
}


TOOL_SCHEMAS = {
    "classify_sections": CLASSIFY_SECTIONS_TOOL["input_schema"],
    "extract_ie_criteria": EXTRACT_IE_CRITERIA_TOOL["input_schema"],
    "extract_visit_schedule": EXTRACT_VISIT_SCHEDULE_TOOL["input_schema"],
    "extract_procedures": EXTRACT_PROCEDURES_TOOL["input_schema"],
    "extract_endpoints": EXTRACT_ENDPOINTS_TOOL["input_schema"],
}

_TOOL_BY_NAME = {
    "classify_sections": CLASSIFY_SECTIONS_TOOL,
    "extract_ie_criteria": EXTRACT_IE_CRITERIA_TOOL,
    "extract_visit_schedule": EXTRACT_VISIT_SCHEDULE_TOOL,
    "extract_procedures": EXTRACT_PROCEDURES_TOOL,
    "extract_endpoints": EXTRACT_ENDPOINTS_TOOL,
}


# ---------------------------------------------------------------------------
# Base pipeline (provider-agnostic orchestration)
# ---------------------------------------------------------------------------

class BaseExtractionPipeline(ABC):
    """
    Base class for the 3-agent extraction pipeline.

    Subclasses implement `_call_llm()` and `model_name` for their specific backend.
    The orchestration here (section classification → 4 agents → enhancements →
    amendment risk → enrollment projection → assemble) is shared by all providers.
    """

    MAX_SECTION_CHARS = 80_000

    def __init__(self, parsed_doc: ParsedDocument):
        self.doc = parsed_doc
        self._progress_callback: Optional[Callable] = None

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier for metadata."""
        ...

    @abstractmethod
    def _call_llm(self, user_prompt: str, tool_name: str) -> dict:
        """
        Call the LLM and return structured JSON matching the schema for tool_name.
        """
        ...

    def set_progress_callback(self, callback: Callable[[str, float], None]):
        self._progress_callback = callback

    def _update_progress(self, step: str, fraction: float):
        if self._progress_callback:
            self._progress_callback(step, fraction)

    # --- Section assembly ------------------------------------------------

    def _get_section_text(self, section_map: dict, category: str) -> str:
        info = section_map.get(category, {})
        page_numbers = info.get("page_numbers", [])
        section_titles = info.get("section_titles", [])

        if not page_numbers and not section_titles:
            return ""

        texts = []
        for page in self.doc.pages:
            if page.page_number in page_numbers:
                texts.append(f"\n--- Page {page.page_number} ---\n")
                texts.append(page.raw_text)
                for table in page.tables:
                    texts.append(f"\n[TABLE on page {page.page_number}]")
                    if table.headers:
                        texts.append(" | ".join(table.headers))
                    for row in table.rows:
                        texts.append(" | ".join(row))
                continue

            for block in page.text_blocks:
                for st in section_titles:
                    if st.lower() in " ".join(block.section_path).lower():
                        texts.append(f"\n--- Page {page.page_number} ---\n")
                        texts.append(page.raw_text)
                        break

        full_text = "\n".join(texts)
        if len(full_text) > self.MAX_SECTION_CHARS:
            full_text = full_text[: self.MAX_SECTION_CHARS] + "\n\n[TEXT TRUNCATED]"
        return full_text

    def _heuristic_section_map(self) -> dict:
        section_map = {
            "ie_criteria": {"section_titles": [], "page_numbers": []},
            "endpoints": {"section_titles": [], "page_numbers": []},
            "schedule": {"section_titles": [], "page_numbers": []},
            "procedures": {"section_titles": [], "page_numbers": []},
        }

        ie_keywords = ["inclusion", "exclusion", "eligibility", "criteria"]
        endpoint_keywords = ["endpoint", "objective", "primary endpoint"]
        schedule_keywords = ["schedule of", "time and events", "activities"]
        procedure_keywords = ["procedure", "biopsy", "assessment", "specimen"]

        for section in self.doc.section_hierarchy:
            title_lower = section["title"].lower()
            page = section["page_number"]

            if any(kw in title_lower for kw in ie_keywords):
                section_map["ie_criteria"]["section_titles"].append(section["title"])
                section_map["ie_criteria"]["page_numbers"].append(page)
            if any(kw in title_lower for kw in endpoint_keywords):
                section_map["endpoints"]["section_titles"].append(section["title"])
                section_map["endpoints"]["page_numbers"].append(page)
            if any(kw in title_lower for kw in schedule_keywords):
                section_map["schedule"]["section_titles"].append(section["title"])
                section_map["schedule"]["page_numbers"].append(page)
            if any(kw in title_lower for kw in procedure_keywords):
                section_map["procedures"]["section_titles"].append(section["title"])
                section_map["procedures"]["page_numbers"].append(page)

        return section_map

    def _build_provenance(
        self,
        metric_name: str,
        display_label: str,
        value,
        confidence: float,
        citations_data: list[dict],
        reasoning: str = "",
        is_estimated: bool = False,
    ) -> ProvenanceRecord:
        citations = []
        for c in citations_data:
            citations.append(
                SourceCitation(
                    quote=c.get("source_quote", c.get("quote", "")),
                    page_number=c.get("page_number", 0),
                    confidence_score=confidence,
                    source_type=SourceType.TEXT,
                )
            )
        return ProvenanceRecord(
            metric_name=metric_name,
            value=value,
            display_label=display_label,
            confidence_score=confidence,
            citations=citations,
            reasoning=reasoning,
            is_estimated=is_estimated,
        )

    def _assemble(
        self,
        ie_result: dict,
        visit_result: dict,
        procedure_result: dict,
        endpoint_result: dict,
    ) -> ExtractionResult:
        ie_count = ie_result.get("total_ie_count", 0)
        endpoints_count = endpoint_result.get("total_endpoints_count", 0)
        total_visits = visit_result.get("total_visits", 0)
        invasive_count = procedure_result.get("total_invasive_count", 0)

        protocol_data = {
            "id": "UPLOADED",
            "name": "Uploaded Protocol",
            "phase": "",
            "therapeutic_area": "Oncology",
            "complexity_metrics": {
                "ie_criteria_count": ie_count,
                "endpoints_count": endpoints_count,
                "sites_count": 0,
                "amendments_predicted": 0,
            },
            "patient_burden": {
                "total_visits": total_visits,
                "invasive_procedures": invasive_count,
                "patient_reported_outcomes": 0,
                "hospitalization_days": 0,
            },
            "site_burden": {
                "staff_hours_per_patient": 0,
                "data_points_per_visit": 0,
                "sample_shipments": 0,
            },
            "rwd_insights": [],
        }

        provenance = {}

        ie_citations = ie_result.get("inclusion_criteria", []) + ie_result.get(
            "exclusion_criteria", []
        )
        provenance["ie_criteria_count"] = self._build_provenance(
            "ie_criteria_count",
            "I/E Criteria Count",
            ie_count,
            ie_result.get("confidence_score", 0.0),
            ie_citations[:5],
            reasoning=ie_result.get("reasoning", ""),
        )

        all_endpoints = (
            endpoint_result.get("primary_endpoints", [])
            + endpoint_result.get("secondary_endpoints", [])
            + endpoint_result.get("exploratory_endpoints", [])
        )
        provenance["endpoints_count"] = self._build_provenance(
            "endpoints_count",
            "Endpoints Count",
            endpoints_count,
            endpoint_result.get("confidence_score", 0.0),
            all_endpoints[:5],
            reasoning=endpoint_result.get("reasoning", ""),
        )

        visit_citations = []
        if visit_result.get("source_quote"):
            visit_citations.append(
                {
                    "source_quote": visit_result["source_quote"],
                    "page_number": (
                        visit_result.get("source_page_numbers", [0])[0]
                        if visit_result.get("source_page_numbers")
                        else 0
                    ),
                }
            )
        provenance["total_visits"] = self._build_provenance(
            "total_visits",
            "Total Visits",
            total_visits,
            visit_result.get("confidence_score", 0.0),
            visit_citations,
            reasoning=visit_result.get("reasoning", ""),
        )

        provenance["invasive_procedures"] = self._build_provenance(
            "invasive_procedures",
            "Invasive Procedures",
            invasive_count,
            procedure_result.get("confidence_score", 0.0),
            procedure_result.get("invasive_procedures", [])[:5],
            reasoning=procedure_result.get("reasoning", ""),
        )

        return ExtractionResult(
            protocol_data=protocol_data,
            provenance=provenance,
            ie_criteria_detail=(
                ie_result.get("inclusion_criteria", [])
                + ie_result.get("exclusion_criteria", [])
            ),
            endpoints_detail=all_endpoints,
            visit_schedule_detail=visit_result.get("visit_names", []),
            source_filename="",
            extraction_timestamp=datetime.now(timezone.utc).isoformat(),
            model_used=self.model_name,
            total_pages=self.doc.total_pages,
        )

    # --- Agent methods (shared orchestration) ----------------------------

    def _classify_sections(self) -> dict:
        prompt = build_router_prompt(self.doc.section_hierarchy)
        result = self._call_llm(prompt, "classify_sections")
        if not result:
            return self._heuristic_section_map()
        return result

    def _run_logic_agent(self, section_text: str) -> dict:
        if not section_text:
            return {
                "total_ie_count": 0,
                "confidence_score": 0.0,
                "inclusion_criteria": [],
                "exclusion_criteria": [],
                "reasoning": "No I/E criteria section found in document.",
            }
        prompt = build_extraction_prompt(LOGIC_AGENT_PROMPT, section_text)
        return self._call_llm(prompt, "extract_ie_criteria")

    def _run_table_agent(self, section_text: str) -> dict:
        if not section_text:
            return {
                "total_visits": 0,
                "confidence_score": 0.0,
                "reasoning": "No schedule section found in document.",
            }
        prompt = build_extraction_prompt(TABLE_AGENT_PROMPT, section_text)
        return self._call_llm(prompt, "extract_visit_schedule")

    def _run_temporal_agent(self, section_text: str) -> dict:
        if not section_text:
            return {
                "total_invasive_count": 0,
                "confidence_score": 0.0,
                "invasive_procedures": [],
                "burden_spikes": [],
                "reasoning": "No procedures section found in document.",
            }
        prompt = build_extraction_prompt(TEMPORAL_AGENT_PROMPT, section_text)
        return self._call_llm(prompt, "extract_procedures")

    def _extract_endpoints(self, section_text: str) -> dict:
        if not section_text:
            return {
                "total_endpoints_count": 0,
                "confidence_score": 0.0,
                "primary_endpoints": [],
                "secondary_endpoints": [],
                "exploratory_endpoints": [],
                "reasoning": "No endpoints section found in document.",
            }
        prompt = build_extraction_prompt(ENDPOINTS_PROMPT, section_text)
        return self._call_llm(prompt, "extract_endpoints")

    def run(self, progress_callback: Optional[Callable] = None) -> ExtractionResult:
        """Execute the full extraction pipeline."""
        if progress_callback:
            self.set_progress_callback(progress_callback)

        self._update_progress("Analyzing document structure...", 0.10)
        section_map = self._classify_sections()

        self._update_progress("Preparing document sections...", 0.20)
        ie_text = self._get_section_text(section_map, "ie_criteria")
        schedule_text = self._get_section_text(section_map, "schedule")
        procedures_text = self._get_section_text(section_map, "procedures")
        endpoints_text = self._get_section_text(section_map, "endpoints")

        if not procedures_text and schedule_text:
            procedures_text = schedule_text

        self._update_progress("Logic Agent: Extracting I/E criteria...", 0.30)
        ie_result = self._run_logic_agent(ie_text)

        self._update_progress("Table Agent: Extracting visit schedule...", 0.50)
        visit_result = self._run_table_agent(schedule_text)

        self._update_progress("Temporal Agent: Mapping procedures...", 0.65)
        procedure_result = self._run_temporal_agent(procedures_text)

        self._update_progress("Extracting study endpoints...", 0.80)
        endpoint_result = self._extract_endpoints(endpoints_text)

        self._update_progress("Assembling extraction results...", 0.88)
        result = self._assemble(ie_result, visit_result, procedure_result, endpoint_result)

        self._update_progress("Running pillar enhancements...", 0.90)
        enhancements = run_pillar_enhancements(ie_result, visit_result, procedure_result)
        enhancement_provenance = build_enhancement_provenance(enhancements)
        result.provenance.update(enhancement_provenance)

        pw = enhancements.procedure_weights
        result.protocol_data["procedure_weight_summary"] = {
            "total_patient_minutes": pw.total_patient_minutes,
            "mapped_count": len(pw.mapped_procedures),
            "unmapped_count": len(pw.unmapped_procedures),
            "coverage_pct": pw.coverage_pct,
            "top_procedures": [
                {"procedure": m["matched_to"], "category": m["category"],
                 "minutes": m["total_minutes"], "count": m["count"]}
                for m in sorted(pw.mapped_procedures, key=lambda x: x["total_minutes"], reverse=True)[:5]
            ],
        }
        result.protocol_data["burden_spikes"] = [
            {"visit_name": s.visit_name, "total_hours": s.total_hours,
             "invasive_count": s.invasive_count, "procedures": s.procedures,
             "reason": s.reason}
            for s in enhancements.burden_spikes
        ]
        result.protocol_data["population_impacts"] = [
            {"criterion_text": p.criterion_text, "impact_key": p.impact_key,
             "impact_pct": p.impact_pct, "description": p.description,
             "suggestion": p.suggestion, "page_number": p.page_number}
            for p in enhancements.population_impacts
        ]
        result.protocol_data["sequencing_risks"] = [
            {"procedure_a": r.procedure_a, "procedure_b": r.procedure_b,
             "gap_days": r.gap_days, "risk_description": r.risk_description,
             "page_number": r.page_number}
            for r in enhancements.sequencing_risks
        ]

        self._update_progress("Evaluating amendment risk patterns...", 0.92)
        amendment_risk = evaluate_amendment_risk(result)
        amendment_provenance = build_amendment_provenance(amendment_risk)
        result.provenance.update(amendment_provenance)
        result.protocol_data["amendment_risk"] = {
            "score": amendment_risk.score,
            "tier": amendment_risk.tier,
            "rules_evaluated": amendment_risk.rules_evaluated,
            "rules_triggered": amendment_risk.rules_triggered,
            "top_findings": [
                {
                    "rule_id": f.rule_id,
                    "pattern": f.pattern,
                    "weight": f.weight,
                    "occurrences": f.occurrences,
                    "matched_text": f.matched_text,
                    "page_number": f.page_number,
                    "common_amendment": f.common_amendment,
                    "mitigation": f.mitigation,
                }
                for f in amendment_risk.top_findings
            ],
        }

        self._update_progress("Projecting enrollment rate...", 0.96)
        enrollment = project_enrollment(result)
        enrollment_provenance = build_enrollment_provenance(enrollment)
        result.provenance.update(enrollment_provenance)
        result.protocol_data["enrollment_projection"] = {
            "rate_per_site_per_month": enrollment.rate_per_site_per_month,
            "confidence_interval_80": enrollment.confidence_interval_80,
            "reference_trials": enrollment.reference_trials,
            "top_restrictive_criteria": enrollment.top_restrictive_criteria,
        }

        self._update_progress("Extraction complete.", 1.0)
        return result
