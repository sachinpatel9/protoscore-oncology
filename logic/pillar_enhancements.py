"""
Enhanced Pillar A/B/C post-processing for ProtoScore V2.

All enhancements are deterministic Python operating on already-extracted data.
No LLM calls. Configurable via JSON data files.

FR-A1.3 (ENHANCED): Procedure Weight Mapping — configurable time-burden taxonomy
FR-A1.5 (NEW):      Visit Clustering / Burden Spikes — flag high-burden visits
FR-B2.5 (ENHANCED): Population Impact Estimates — per-criterion exclusion rates
FR-C3.3 (NEW):      Invasive Procedure Sequencing Risk — flag compounded burden
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from logic.provenance import (
    ExtractionResult,
    ProvenanceRecord,
    SourceCitation,
    SourceType,
)

logger = logging.getLogger(__name__)

WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "data" / "procedure_weights.json"

# Population impact reference table for FR-B2.5
# Source: published literature + expert clinical operations review
POPULATION_IMPACT_TABLE = {
    "ecog_0": {
        "patterns": [r"ECOG.*(?:=|of|:)?\s*0(?!\s*[-–]\s*[12])"],
        "impact_pct": 40,
        "description": "ECOG 0 only — excludes ~40% of standard oncology SOC population",
        "suggestion": "Consider expanding to ECOG 0-1 to improve enrollment rate.",
    },
    "ecog_0_1": {
        "patterns": [r"ECOG.*0\s*[-–]\s*1", r"ECOG.*[≤<]\s*1"],
        "impact_pct": 15,
        "description": "ECOG 0-1 — excludes ~15% of patients (ECOG 2+)",
        "suggestion": None,
    },
    "prior_therapy_naive": {
        "patterns": [
            r"treatment[\s-]?na[iï]ve",
            r"no\s+prior.*(?:systemic|anti[\s-]?cancer|chemo)",
            r"(?:first|1st|1)[\s-]?line\s+(?:only|treatment|therapy)",
        ],
        "impact_pct": 30,
        "description": "First-line only — excludes ~30% of patients with prior therapy",
        "suggestion": "Consider expanding to 1-2 prior lines.",
    },
    "prior_therapy_3plus": {
        "patterns": [r"[≥>]\s*3.*(?:prior|previous|line)", r"(?:third|3rd|3)\s+line\s+or\s+later"],
        "impact_pct": 60,
        "description": "3+ prior lines — excludes ~60% of the general oncology population",
        "suggestion": None,
    },
    "pdl1_required": {
        "patterns": [r"PD[-\s]?L1.*(?:positive|[≥>]\s*\d|TPS|CPS|expression)"],
        "impact_pct": 35,
        "description": "PD-L1 selection — narrows eligible pool by ~35%",
        "suggestion": "Consider enrolling all-comers with PD-L1 stratification.",
    },
    "brca_required": {
        "patterns": [r"BRCA\d?\s+(?:mutation|positive|alteration)"],
        "impact_pct": 75,
        "description": "BRCA mutation required — limits pool to ~10-25% of patients",
        "suggestion": None,
    },
    "msi_required": {
        "patterns": [r"MSI[-\s]?H", r"dMMR", r"microsatellite\s+instab"],
        "impact_pct": 85,
        "description": "MSI-H/dMMR selection — prevalence ~5-15% across solid tumors",
        "suggestion": None,
    },
    "lab_strict_uln": {
        "patterns": [r"[<≤]\s*1\.?0?\s*[x×]\s*(?:ULN|upper\s+limit)"],
        "impact_pct": 15,
        "description": "Lab threshold at exact ULN — increases screen failure by ~15%",
        "suggestion": "Add 10% buffer (1.0x → 1.1x ULN).",
    },
    "lvef_required": {
        "patterns": [r"LVEF\s*[≥>]\s*\d+", r"ejection\s+fraction\s*[≥>]\s*\d+"],
        "impact_pct": 10,
        "description": "LVEF threshold — excludes ~10% of patients",
        "suggestion": None,
    },
    "cns_exclusion": {
        "patterns": [r"(?:brain|CNS)\s+metastas(?:is|es)\s+(?:are\s+)?excluded",
                     r"no\s+(?:known\s+)?(?:brain|CNS)\s+metastas"],
        "impact_pct": 20,
        "description": "CNS metastases excluded — excludes ~20% in certain tumor types",
        "suggestion": "Consider allowing treated, stable CNS metastases.",
    },
    "autoimmune_exclusion": {
        "patterns": [r"(?:autoimmune|auto-immune)\s+disease\s+(?:is\s+)?excluded",
                     r"no\s+(?:active\s+)?autoimmune"],
        "impact_pct": 10,
        "description": "Autoimmune disease exclusion — excludes ~10% of IO-eligible patients",
        "suggestion": None,
    },
}


# ---------------------------------------------------------------------------
# FR-A1.3: Procedure Weight Mapping
# ---------------------------------------------------------------------------

def load_procedure_weights() -> list[dict]:
    """Load procedure weight taxonomy from JSON config."""
    try:
        with open(WEIGHTS_PATH) as f:
            data = json.load(f)
        return data.get("procedures", [])
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Error loading procedure weights: {e}")
        return []


def _match_procedure(name: str, taxonomy: list[dict]) -> dict | None:
    """Match an extracted procedure name to the taxonomy via aliases."""
    name_lower = name.lower().strip()
    for proc in taxonomy:
        # Exact name match
        if name_lower == proc["name"].lower():
            return proc
        # Alias match
        for alias in proc.get("aliases", []):
            if alias.lower() in name_lower or name_lower in alias.lower():
                return proc
    return None


@dataclass
class ProcedureWeightResult:
    """Result of mapping extracted procedures to time-burden weights."""
    mapped_procedures: list[dict] = field(default_factory=list)
    unmapped_procedures: list[str] = field(default_factory=list)
    total_patient_minutes: float = 0.0
    coverage_pct: float = 0.0


def map_procedure_weights(
    procedure_result: dict,
    visit_result: dict,
) -> ProcedureWeightResult:
    """
    FR-A1.3: Map extracted procedures to time-burden weights.

    Converts raw procedure counts into estimated patient-hours per visit.
    """
    taxonomy = load_procedure_weights()
    if not taxonomy:
        return ProcedureWeightResult()

    procedures = procedure_result.get("invasive_procedures", [])
    schedule = visit_result.get("schedule_table", {})

    mapped = []
    unmapped = []
    total_minutes = 0.0

    # Map procedures from invasive_procedures list
    for proc in procedures:
        proc_name = proc.get("procedure_name", "")
        count = proc.get("count", 1)
        match = _match_procedure(proc_name, taxonomy)
        if match:
            minutes = match["minutes"] * count
            total_minutes += minutes
            mapped.append({
                "procedure": proc_name,
                "matched_to": match["name"],
                "category": match["category"],
                "minutes_each": match["minutes"],
                "count": count,
                "total_minutes": minutes,
                "invasive": match["invasive"],
                "source_page": proc.get("page_number", 0),
            })
        else:
            unmapped.append(proc_name)

    # Also try to map from the schedule table rows
    if schedule:
        for proc_name in schedule.keys():
            # Skip if already mapped
            if any(m["procedure"].lower() == proc_name.lower() for m in mapped):
                continue
            match = _match_procedure(proc_name, taxonomy)
            if match:
                # Count visits where this procedure occurs
                visits_with_proc = sum(
                    1 for v in schedule[proc_name].values()
                    if v and v.strip().upper() in ("X", "YES", "1", "✓", "✗")
                )
                if visits_with_proc > 0:
                    minutes = match["minutes"] * visits_with_proc
                    total_minutes += minutes
                    mapped.append({
                        "procedure": proc_name,
                        "matched_to": match["name"],
                        "category": match["category"],
                        "minutes_each": match["minutes"],
                        "count": visits_with_proc,
                        "total_minutes": minutes,
                        "invasive": match["invasive"],
                        "source_page": 0,
                    })

    total_procs = len(mapped) + len(unmapped)
    coverage = (len(mapped) / total_procs * 100) if total_procs > 0 else 0.0

    return ProcedureWeightResult(
        mapped_procedures=mapped,
        unmapped_procedures=unmapped,
        total_patient_minutes=total_minutes,
        coverage_pct=round(coverage, 1),
    )


# ---------------------------------------------------------------------------
# FR-A1.5: Visit Clustering / Burden Spikes
# ---------------------------------------------------------------------------

@dataclass
class BurdenSpike:
    """A single visit flagged as a burden spike."""
    visit_name: str
    total_hours: float
    invasive_count: int
    procedures: list[str]
    reason: str  # "invasive_count" or "time_threshold" or "both"


def detect_burden_spikes(
    procedure_result: dict,
    visit_result: dict,
    weight_result: ProcedureWeightResult,
) -> list[BurdenSpike]:
    """
    FR-A1.5: Flag visits where >=3 invasive procedures or >=4 total hours.

    Analyzes the schedule table to identify visits with concentrated burden.
    """
    spikes = []
    schedule = visit_result.get("schedule_table", {})

    if not schedule:
        # Fall back to burden_spikes from temporal agent
        for spike in procedure_result.get("burden_spikes", []):
            hours = spike.get("estimated_hours", 0)
            procs = spike.get("procedures_in_visit", [])
            if hours >= 4 or len(procs) >= 3:
                spikes.append(BurdenSpike(
                    visit_name=spike.get("visit_name", "Unknown"),
                    total_hours=hours,
                    invasive_count=len(procs),
                    procedures=procs,
                    reason="time_threshold" if hours >= 4 else "invasive_count",
                ))
        return spikes

    taxonomy = load_procedure_weights()

    # Build per-visit analysis from schedule table
    visit_names = set()
    for proc_visits in schedule.values():
        visit_names.update(proc_visits.keys())

    for visit in sorted(visit_names):
        visit_procs = []
        visit_invasive = 0
        visit_minutes = 0.0

        for proc_name, visits_map in schedule.items():
            mark = visits_map.get(visit, "").strip().upper()
            if mark in ("X", "YES", "1", "✓", "✗"):
                visit_procs.append(proc_name)
                match = _match_procedure(proc_name, taxonomy)
                if match:
                    visit_minutes += match["minutes"]
                    if match["invasive"]:
                        visit_invasive += 1
                else:
                    visit_minutes += 20  # Default estimate

        visit_hours = visit_minutes / 60.0

        if visit_invasive >= 3 and visit_hours >= 4:
            reason = "both"
        elif visit_invasive >= 3:
            reason = "invasive_count"
        elif visit_hours >= 4:
            reason = "time_threshold"
        else:
            continue

        spikes.append(BurdenSpike(
            visit_name=visit,
            total_hours=round(visit_hours, 1),
            invasive_count=visit_invasive,
            procedures=visit_procs,
            reason=reason,
        ))

    return spikes


# ---------------------------------------------------------------------------
# FR-B2.5: Population Impact Estimates
# ---------------------------------------------------------------------------

@dataclass
class PopulationImpact:
    """Population impact for a single restrictive criterion."""
    criterion_text: str
    impact_key: str
    impact_pct: int
    description: str
    suggestion: str | None
    page_number: int
    source_quote: str


def estimate_population_impact(
    ie_result: dict,
) -> list[PopulationImpact]:
    """
    FR-B2.5: For criteria containing restrictive entities, append estimated
    population exclusion rates from the internal reference table.
    """
    impacts = []
    seen_keys = set()

    all_criteria = (
        ie_result.get("inclusion_criteria", [])
        + ie_result.get("exclusion_criteria", [])
    )

    for criterion in all_criteria:
        text = f"{criterion.get('text', '')} {criterion.get('source_quote', '')}"
        page = criterion.get("page_number", 0)

        for key, ref in POPULATION_IMPACT_TABLE.items():
            if key in seen_keys:
                continue
            for pattern in ref["patterns"]:
                try:
                    if re.search(pattern, text, re.IGNORECASE):
                        impacts.append(PopulationImpact(
                            criterion_text=criterion.get("text", "")[:120],
                            impact_key=key,
                            impact_pct=ref["impact_pct"],
                            description=ref["description"],
                            suggestion=ref.get("suggestion"),
                            page_number=page,
                            source_quote=criterion.get("source_quote", "")[:120],
                        ))
                        seen_keys.add(key)
                        break
                except re.error:
                    pass

    # Sort by impact descending
    impacts.sort(key=lambda x: x.impact_pct, reverse=True)
    return impacts


# ---------------------------------------------------------------------------
# FR-C3.3: Invasive Procedure Sequencing Risk
# ---------------------------------------------------------------------------

@dataclass
class SequencingRisk:
    """A pair of invasive procedures flagged for compounded burden."""
    procedure_a: str
    procedure_b: str
    gap_days: int
    risk_description: str
    page_number: int


def detect_sequencing_risks(
    procedure_result: dict,
) -> list[SequencingRisk]:
    """
    FR-C3.3: Flag biopsy-class procedures scheduled within 14 calendar days
    of a PK assessment or another biopsy.
    """
    risks = []
    procedures = procedure_result.get("invasive_procedures", [])

    biopsy_keywords = ["biopsy", "aspirate", "lumbar puncture", "leukapheresis"]
    pk_keywords = ["pk", "pharmacokinetic"]

    biopsy_procs = []
    pk_procs = []

    for proc in procedures:
        name_lower = proc.get("procedure_name", "").lower()
        timing = proc.get("timing", "").lower()
        page = proc.get("page_number", 0)

        is_biopsy = any(kw in name_lower for kw in biopsy_keywords)
        is_pk = any(kw in name_lower for kw in pk_keywords)

        if is_biopsy:
            biopsy_procs.append(proc)
        if is_pk:
            pk_procs.append(proc)

    # Check biopsy-to-biopsy proximity
    for i, bp_a in enumerate(biopsy_procs):
        for bp_b in biopsy_procs[i + 1:]:
            timing_a = bp_a.get("timing", "")
            timing_b = bp_b.get("timing", "")

            gap = _estimate_day_gap(timing_a, timing_b)
            if gap is not None and gap <= 14:
                risks.append(SequencingRisk(
                    procedure_a=bp_a["procedure_name"],
                    procedure_b=bp_b["procedure_name"],
                    gap_days=gap,
                    risk_description=(
                        f"{bp_a['procedure_name']} and {bp_b['procedure_name']} "
                        f"are scheduled within {gap} days — compounded invasive burden."
                    ),
                    page_number=bp_a.get("page_number", 0),
                ))

    # Check biopsy-to-PK proximity
    for bp in biopsy_procs:
        for pk in pk_procs:
            timing_bp = bp.get("timing", "")
            timing_pk = pk.get("timing", "")

            gap = _estimate_day_gap(timing_bp, timing_pk)
            if gap is not None and gap <= 14:
                risks.append(SequencingRisk(
                    procedure_a=bp["procedure_name"],
                    procedure_b=pk["procedure_name"],
                    gap_days=gap,
                    risk_description=(
                        f"{bp['procedure_name']} and {pk['procedure_name']} "
                        f"are scheduled within {gap} days — compounded patient burden."
                    ),
                    page_number=bp.get("page_number", 0),
                ))

    return risks


def _estimate_day_gap(timing_a: str, timing_b: str) -> int | None:
    """
    Estimate the calendar day gap between two timing strings.

    Handles formats like "Week 6", "Day 1", "C1D1", "Cycle 2 Day 15".
    Returns None if gap cannot be determined.
    """
    day_a = _timing_to_day(timing_a)
    day_b = _timing_to_day(timing_b)

    if day_a is not None and day_b is not None:
        return abs(day_b - day_a)
    return None


def _timing_to_day(timing: str) -> int | None:
    """Convert a timing string to an approximate study day."""
    if not timing:
        return None
    timing_lower = timing.lower().strip()

    # "Day X" or "D X"
    match = re.search(r"day\s*(\d+)", timing_lower)
    if match:
        return int(match.group(1))

    # "Week X" → Day = Week * 7
    match = re.search(r"week\s*(\d+)", timing_lower)
    if match:
        return int(match.group(1)) * 7

    # "CxDy" pattern (e.g., C1D1, C2D15)
    match = re.search(r"c(?:ycle)?\s*(\d+)\s*d(?:ay)?\s*(\d+)", timing_lower)
    if match:
        cycle = int(match.group(1))
        day = int(match.group(2))
        return (cycle - 1) * 21 + day  # Assume 21-day cycles as default

    # "Month X" → Day = Month * 30
    match = re.search(r"month\s*(\d+)", timing_lower)
    if match:
        return int(match.group(1)) * 30

    return None


# ---------------------------------------------------------------------------
# Unified enhancement runner
# ---------------------------------------------------------------------------

@dataclass
class PillarEnhancementResult:
    """Combined result of all pillar enhancements."""
    procedure_weights: ProcedureWeightResult
    burden_spikes: list[BurdenSpike]
    population_impacts: list[PopulationImpact]
    sequencing_risks: list[SequencingRisk]


def run_pillar_enhancements(
    ie_result: dict,
    visit_result: dict,
    procedure_result: dict,
) -> PillarEnhancementResult:
    """
    Run all Pillar A/B/C enhancements on extracted data.

    This is called from the extraction pipeline after the LLM agents
    have produced their results but before final assembly.
    """
    # FR-A1.3: Procedure weight mapping
    weight_result = map_procedure_weights(procedure_result, visit_result)

    # FR-A1.5: Burden spike detection
    spikes = detect_burden_spikes(procedure_result, visit_result, weight_result)

    # FR-B2.5: Population impact estimates
    pop_impacts = estimate_population_impact(ie_result)

    # FR-C3.3: Sequencing risk detection
    seq_risks = detect_sequencing_risks(procedure_result)

    return PillarEnhancementResult(
        procedure_weights=weight_result,
        burden_spikes=spikes,
        population_impacts=pop_impacts,
        sequencing_risks=seq_risks,
    )


def build_enhancement_provenance(
    enhancements: PillarEnhancementResult,
) -> dict[str, ProvenanceRecord]:
    """Build provenance records for pillar enhancements."""
    provenance = {}

    # Burden spikes provenance
    if enhancements.burden_spikes:
        spike_citations = []
        for spike in enhancements.burden_spikes:
            spike_citations.append(SourceCitation(
                quote=f"{spike.visit_name}: {', '.join(spike.procedures[:3])} ({spike.total_hours}h)",
                page_number=0,
                confidence_score=1.0,
                source_type=SourceType.INFERRED,
            ))
        provenance["burden_spikes"] = ProvenanceRecord(
            metric_name="burden_spikes",
            value=len(enhancements.burden_spikes),
            display_label="Burden Spikes Detected",
            confidence_score=1.0,
            citations=spike_citations[:3],
            reasoning=(
                f"{len(enhancements.burden_spikes)} visit(s) flagged: "
                + "; ".join(
                    f"{s.visit_name} ({s.total_hours}h, {s.invasive_count} invasive)"
                    for s in enhancements.burden_spikes[:3]
                )
            ),
        )

    # Sequencing risks provenance
    if enhancements.sequencing_risks:
        seq_citations = []
        for risk in enhancements.sequencing_risks:
            seq_citations.append(SourceCitation(
                quote=risk.risk_description,
                page_number=risk.page_number,
                confidence_score=1.0,
                source_type=SourceType.INFERRED,
            ))
        provenance["sequencing_risks"] = ProvenanceRecord(
            metric_name="sequencing_risks",
            value=len(enhancements.sequencing_risks),
            display_label="Sequencing Risks Detected",
            confidence_score=1.0,
            citations=seq_citations[:3],
            reasoning=(
                f"{len(enhancements.sequencing_risks)} compounded burden risk(s): "
                + "; ".join(r.risk_description[:80] for r in enhancements.sequencing_risks[:3])
            ),
        )

    # Procedure weight coverage provenance
    pw = enhancements.procedure_weights
    if pw.mapped_procedures:
        provenance["procedure_weight_coverage"] = ProvenanceRecord(
            metric_name="procedure_weight_coverage",
            value=pw.coverage_pct,
            display_label="Procedure Weight Coverage",
            confidence_score=1.0,
            citations=[],
            reasoning=(
                f"Mapped {len(pw.mapped_procedures)} procedures to time-burden weights "
                f"({pw.coverage_pct}% coverage). "
                f"Total estimated patient time: {pw.total_patient_minutes:.0f} minutes."
            ),
        )

    return provenance
