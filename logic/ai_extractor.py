"""
AI extraction pipeline for ProtoScore V2.

Three-agent architecture for structured extraction:
- Table Agent: Schedule of Assessments → visit count, procedures per visit
- Logic Agent: I/E Criteria → criteria count, conditional logic, restrictiveness
- Temporal Agent: Invasive procedures → temporal mapping, burden spikes

Two provider backends:
- Claude API (tool_use) — highest quality
- Ollama local LLM (JSON-mode prompts) — offline / data-sensitive use

The LLM fills a JSON Feature Vector; Python calculates the score (safety valve).
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Callable, Optional

import anthropic

from logic.pdf_parser import ParsedDocument
from logic.pii_scrubber import scrub_pii
from logic.prompts import (
    SYSTEM_PROMPT,
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
# Claude Tool Schemas (used by Claude API path and as reference for Ollama)
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


# Map tool names to their JSON schemas (reused by Ollama path)
TOOL_SCHEMAS = {
    "classify_sections": CLASSIFY_SECTIONS_TOOL["input_schema"],
    "extract_ie_criteria": EXTRACT_IE_CRITERIA_TOOL["input_schema"],
    "extract_visit_schedule": EXTRACT_VISIT_SCHEDULE_TOOL["input_schema"],
    "extract_procedures": EXTRACT_PROCEDURES_TOOL["input_schema"],
    "extract_endpoints": EXTRACT_ENDPOINTS_TOOL["input_schema"],
}


# ---------------------------------------------------------------------------
# Base Extraction Pipeline (shared logic)
# ---------------------------------------------------------------------------

class BaseExtractionPipeline(ABC):
    """
    Base class for the 3-agent extraction pipeline.

    Subclasses implement _call_llm() for their specific backend.
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

        Args:
            user_prompt: The full prompt to send
            tool_name: One of the TOOL_SCHEMAS keys, identifying expected output shape

        Returns:
            Parsed dict matching the expected schema
        """
        ...

    def set_progress_callback(self, callback: Callable[[str, float], None]):
        self._progress_callback = callback

    def _update_progress(self, step: str, fraction: float):
        if self._progress_callback:
            self._progress_callback(step, fraction)

    # --- Shared section / assembly logic ---

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

    # --- Agent methods (shared orchestration, use _call_llm) ---

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

        # Store enhancement results in protocol_data
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


# ---------------------------------------------------------------------------
# Claude API Pipeline
# ---------------------------------------------------------------------------

class ExtractionPipeline(BaseExtractionPipeline):
    """Claude API extraction using tool_use for structured output."""

    MODEL = "claude-sonnet-4-20250514"

    def __init__(self, api_key: str, parsed_doc: ParsedDocument):
        super().__init__(parsed_doc)
        self.client = anthropic.Anthropic(api_key=api_key)

    @property
    def model_name(self) -> str:
        return self.MODEL

    def _call_llm(self, user_prompt: str, tool_name: str) -> dict:
        scrubbed_prompt, _ = scrub_pii(user_prompt)

        tool_map = {
            "classify_sections": CLASSIFY_SECTIONS_TOOL,
            "extract_ie_criteria": EXTRACT_IE_CRITERIA_TOOL,
            "extract_visit_schedule": EXTRACT_VISIT_SCHEDULE_TOOL,
            "extract_procedures": EXTRACT_PROCEDURES_TOOL,
            "extract_endpoints": EXTRACT_ENDPOINTS_TOOL,
        }

        tool_def = tool_map[tool_name]

        response = self.client.messages.create(
            model=self.MODEL,
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": scrubbed_prompt}],
            tools=[tool_def],
            tool_choice={"type": "tool", "name": tool_name},
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                return block.input

        return {}


# ---------------------------------------------------------------------------
# Ollama Local LLM Pipeline
# ---------------------------------------------------------------------------

class OllamaExtractionPipeline(BaseExtractionPipeline):
    """Ollama local LLM extraction using JSON-mode prompts."""

    def __init__(self, model: str, parsed_doc: ParsedDocument):
        super().__init__(parsed_doc)
        self._model = model

    @property
    def model_name(self) -> str:
        return f"ollama/{self._model}"

    def _call_llm(self, user_prompt: str, tool_name: str) -> dict:
        from logic.ollama_utils import call_ollama_chat

        scrubbed_prompt, _ = scrub_pii(user_prompt)

        # Embed the expected JSON schema in the prompt
        schema = TOOL_SCHEMAS[tool_name]
        schema_instruction = (
            "\n\n---\n"
            "IMPORTANT: Respond with ONLY a valid JSON object matching this exact schema. "
            "Do not include any text before or after the JSON.\n\n"
            f"Required JSON schema:\n```json\n{json.dumps(schema, indent=2)}\n```"
        )

        full_prompt = scrubbed_prompt + schema_instruction

        # First attempt
        try:
            result = call_ollama_chat(
                model=self._model,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=full_prompt,
                json_mode=True,
            )
            if self._validate_result(result, tool_name):
                return result
        except Exception as e:
            logger.warning(f"Ollama first attempt failed for {tool_name}: {e}")

        # Retry with stricter prompt
        logger.info(f"Retrying {tool_name} with stricter prompt")
        strict_prompt = (
            f"You MUST respond with valid JSON only. No explanations.\n\n"
            f"{scrubbed_prompt}\n\n"
            f"Output ONLY this JSON structure:\n{json.dumps(schema, indent=2)}"
        )

        try:
            result = call_ollama_chat(
                model=self._model,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=strict_prompt,
                json_mode=True,
            )
            if result:
                return result
        except Exception as e:
            logger.error(f"Ollama retry failed for {tool_name}: {e}")

        # Return empty defaults on failure
        return self._empty_result(tool_name)

    def _validate_result(self, result: dict, tool_name: str) -> bool:
        """Check that the result has the required fields for the schema."""
        schema = TOOL_SCHEMAS.get(tool_name, {})
        required = schema.get("required", [])
        return all(key in result for key in required)

    def _empty_result(self, tool_name: str) -> dict:
        """Return safe empty defaults when extraction fails."""
        defaults = {
            "classify_sections": {
                "ie_criteria": {"section_titles": [], "page_numbers": []},
                "endpoints": {"section_titles": [], "page_numbers": []},
                "schedule": {"section_titles": [], "page_numbers": []},
                "procedures": {"section_titles": [], "page_numbers": []},
            },
            "extract_ie_criteria": {
                "total_ie_count": 0,
                "confidence_score": 0.0,
                "inclusion_criteria": [],
                "exclusion_criteria": [],
                "reasoning": "Extraction failed — local model could not parse this section.",
            },
            "extract_visit_schedule": {
                "total_visits": 0,
                "confidence_score": 0.0,
                "reasoning": "Extraction failed — local model could not parse this section.",
            },
            "extract_procedures": {
                "total_invasive_count": 0,
                "confidence_score": 0.0,
                "invasive_procedures": [],
                "burden_spikes": [],
                "reasoning": "Extraction failed — local model could not parse this section.",
            },
            "extract_endpoints": {
                "total_endpoints_count": 0,
                "confidence_score": 0.0,
                "primary_endpoints": [],
                "secondary_endpoints": [],
                "exploratory_endpoints": [],
                "reasoning": "Extraction failed — local model could not parse this section.",
            },
        }
        return defaults.get(tool_name, {})
