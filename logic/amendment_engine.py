"""
Protocol Amendment Risk Engine (Pillar D).

Rule-based Python engine that evaluates parsed protocol data against a
configurable Amendment Risk Ruleset (data/amendment_rules.json).

Per FR 0.1: The LLM fills the JSON Feature Vector. This Python engine
calculates all scores deterministically. No LLM-generated scores.

Outputs:
    - Amendment Risk Score (0-100, normalised)
    - Risk Tier (Low / Moderate / High)
    - Top 3 findings with source metadata and mitigation suggestions
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from logic.provenance import ExtractionResult, ProvenanceRecord, SourceCitation, SourceType

logger = logging.getLogger(__name__)

RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "amendment_rules.json"


@dataclass
class AmendmentFinding:
    """A single amendment risk finding."""
    rule_id: str
    pattern: str
    weight: float
    occurrences: int
    matched_text: str
    page_number: int
    common_amendment: str
    mitigation: str

    @property
    def weighted_score(self) -> float:
        return self.weight * self.occurrences


@dataclass
class AmendmentRiskResult:
    """Complete amendment risk assessment."""
    score: float                              # 0-100 normalised
    tier: str                                 # Low / Moderate / High
    findings: list[AmendmentFinding] = field(default_factory=list)
    rules_evaluated: int = 0
    rules_triggered: int = 0

    @property
    def top_findings(self) -> list[AmendmentFinding]:
        """Return top 3 findings ranked by weighted score."""
        return sorted(self.findings, key=lambda f: f.weighted_score, reverse=True)[:3]


def load_amendment_rules() -> list[dict]:
    """Load the amendment ruleset from the JSON config file."""
    try:
        with open(RULES_PATH) as f:
            data = json.load(f)
        return data.get("rules", [])
    except FileNotFoundError:
        logger.error(f"Amendment rules file not found: {RULES_PATH}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in amendment rules: {e}")
        return []


def _get_all_text(result: ExtractionResult) -> str:
    """Concatenate all available protocol text for searching."""
    parts = []
    for crit in result.ie_criteria_detail:
        parts.append(crit.get("text", ""))
        parts.append(crit.get("source_quote", ""))
        parts.append(crit.get("condition_text", ""))
    for ep in result.endpoints_detail:
        parts.append(ep.get("name", ""))
        parts.append(ep.get("description", ""))
        parts.append(ep.get("source_quote", ""))
    return " ".join(p for p in parts if p)


def _get_exclusion_text(result: ExtractionResult) -> str:
    """Get only exclusion criteria text."""
    parts = []
    for crit in result.ie_criteria_detail:
        text = crit.get("text", "").lower()
        # Heuristic: criteria from the exclusion portion
        # The extractor stores them interleaved; check for exclusion markers
        if crit.get("criterion_number", 0) > 0:
            source = crit.get("source_quote", "")
            parts.append(crit.get("text", ""))
            parts.append(source)
    # If we have separate inclusion/exclusion from the extraction, the
    # ie_criteria_detail may contain both. The exclusion criteria are typically
    # in the latter half or have restrictiveness/reasoning fields.
    if not parts:
        return _get_all_text(result)
    return " ".join(p for p in parts if p)


def _search_criteria_text(
    result: ExtractionResult,
    patterns: list[str],
    scope: str = "all",
) -> list[dict]:
    """
    Search criteria text for regex patterns.

    Returns list of matches with matched_text and page_number.
    """
    if scope == "exclusion_only":
        search_items = []
        for crit in result.ie_criteria_detail:
            search_items.append({
                "text": f"{crit.get('text', '')} {crit.get('source_quote', '')}",
                "page": crit.get("page_number", 0),
            })
    else:
        search_items = []
        for crit in result.ie_criteria_detail:
            search_items.append({
                "text": f"{crit.get('text', '')} {crit.get('source_quote', '')}",
                "page": crit.get("page_number", 0),
            })
        for ep in result.endpoints_detail:
            search_items.append({
                "text": f"{ep.get('name', '')} {ep.get('description', '')} {ep.get('source_quote', '')}",
                "page": ep.get("page_number", 0),
            })

    matches = []
    for item in search_items:
        text = item["text"]
        for pattern in patterns:
            try:
                found = re.findall(pattern, text, re.IGNORECASE)
                if found:
                    matched = found[0] if isinstance(found[0], str) else text[:80]
                    matches.append({
                        "matched_text": matched.strip(),
                        "page_number": item["page"],
                        "full_text": text[:200],
                    })
                    break  # One match per item per rule is sufficient
            except re.error:
                logger.warning(f"Invalid regex pattern: {pattern}")
    return matches


def _check_text_absent(result: ExtractionResult, absent_patterns: list[str]) -> bool:
    """Return True if NONE of the patterns are found in the protocol text."""
    all_text = _get_all_text(result)
    for pattern in absent_patterns:
        try:
            if re.search(pattern, all_text, re.IGNORECASE):
                return False
        except re.error:
            pass
    return True


def _evaluate_rule(rule: dict, result: ExtractionResult) -> Optional[AmendmentFinding]:
    """
    Evaluate a single amendment rule against the extraction result.

    Returns an AmendmentFinding if the rule triggers, None otherwise.
    """
    detection = rule.get("detection", {})
    detection_type = detection.get("type", "")

    if detection_type == "criteria_text_match":
        patterns = detection.get("match_patterns", [])
        scope = detection.get("search_scope", "all")
        matches = _search_criteria_text(result, patterns, scope)

        if not matches:
            return None

        # Check indication exclusions (e.g., AMR-01 excludes haematology)
        exclude_indications = detection.get("exclude_indications", [])
        if exclude_indications:
            indication = result.protocol_data.get("therapeutic_area", "").lower()
            phase_indication = result.protocol_data.get("indication", "").lower()
            combined = f"{indication} {phase_indication}"
            for excl in exclude_indications:
                if excl.lower() in combined:
                    return None

        return AmendmentFinding(
            rule_id=rule["rule_id"],
            pattern=rule["pattern"],
            weight=rule["weight"],
            occurrences=len(matches),
            matched_text=matches[0]["matched_text"],
            page_number=matches[0]["page_number"],
            common_amendment=rule["common_amendment"],
            mitigation=rule["mitigation"],
        )

    elif detection_type == "numeric_threshold":
        field_name = detection.get("field", "")
        operator = detection.get("operator", ">")
        threshold = detection.get("threshold", 0)

        # Look up the value in protocol_data
        value = None
        for section in ["patient_burden", "complexity_metrics", "site_burden"]:
            section_data = result.protocol_data.get(section, {})
            if field_name in section_data:
                value = section_data[field_name]
                break

        if value is None:
            return None

        triggered = False
        if operator == ">" and value > threshold:
            triggered = True
        elif operator == ">=" and value >= threshold:
            triggered = True
        elif operator == "<" and value < threshold:
            triggered = True

        if not triggered:
            return None

        # Find source for this field from provenance
        page = 0
        matched = f"{field_name} = {value} (threshold: {operator} {threshold})"
        prov = result.provenance.get(field_name)
        if prov and prov.citations:
            page = prov.citations[0].page_number
            matched = prov.citations[0].quote or matched

        return AmendmentFinding(
            rule_id=rule["rule_id"],
            pattern=rule["pattern"],
            weight=rule["weight"],
            occurrences=1,
            matched_text=matched,
            page_number=page,
            common_amendment=rule["common_amendment"],
            mitigation=rule["mitigation"],
        )

    elif detection_type == "compound_match":
        conditions = detection.get("conditions", [])
        all_met = True
        first_match_text = ""
        first_match_page = 0

        for cond in conditions:
            cond_type = cond.get("type", "")

            if cond_type == "criteria_text_match":
                patterns = cond.get("match_patterns", [])
                matches = _search_criteria_text(result, patterns)
                if not matches:
                    all_met = False
                    break
                if not first_match_text:
                    first_match_text = matches[0]["matched_text"]
                    first_match_page = matches[0]["page_number"]

            elif cond_type == "criteria_text_absent":
                absent_patterns = cond.get("absent_patterns", [])
                if not _check_text_absent(result, absent_patterns):
                    all_met = False
                    break

        if not all_met:
            return None

        return AmendmentFinding(
            rule_id=rule["rule_id"],
            pattern=rule["pattern"],
            weight=rule["weight"],
            occurrences=1,
            matched_text=first_match_text or rule["pattern"],
            page_number=first_match_page,
            common_amendment=rule["common_amendment"],
            mitigation=rule["mitigation"],
        )

    return None


def evaluate_amendment_risk(result: ExtractionResult) -> AmendmentRiskResult:
    """
    Evaluate the full amendment risk for a protocol.

    FR-D5.1: Pattern detection against configurable ruleset.
    FR-D5.2: Score = sum(pattern_weight * occurrence_count), normalised to 0-100.
             Bands: 0-30 = Low | 31-60 = Moderate | 61-100 = High.
    FR-D5.3: Top 3 findings with source metadata and mitigation.

    Args:
        result: ExtractionResult from the extraction pipeline

    Returns:
        AmendmentRiskResult with score, tier, and findings
    """
    rules = load_amendment_rules()
    if not rules:
        return AmendmentRiskResult(score=0.0, tier="Low", rules_evaluated=0, rules_triggered=0)

    findings = []
    for rule in rules:
        try:
            finding = _evaluate_rule(rule, result)
            if finding:
                findings.append(finding)
        except Exception as e:
            logger.warning(f"Error evaluating rule {rule.get('rule_id', '?')}: {e}")

    # FR-D5.2: Calculate raw score
    raw_score = sum(f.weighted_score for f in findings)

    # Normalise to 0-100
    # Max possible raw score = sum of all weights (if all rules fire once)
    max_possible = sum(r["weight"] for r in rules)
    if max_possible > 0:
        normalised = min(100.0, (raw_score / max_possible) * 100.0)
    else:
        normalised = 0.0

    # Determine tier
    if normalised <= 30:
        tier = "Low"
    elif normalised <= 60:
        tier = "Moderate"
    else:
        tier = "High"

    return AmendmentRiskResult(
        score=round(normalised, 1),
        tier=tier,
        findings=findings,
        rules_evaluated=len(rules),
        rules_triggered=len(findings),
    )


def build_amendment_provenance(
    risk_result: AmendmentRiskResult,
) -> dict[str, ProvenanceRecord]:
    """
    Build provenance records for amendment risk findings.

    Returns a dict of ProvenanceRecord keyed by metric name, suitable
    for merging into ExtractionResult.provenance.
    """
    provenance = {}

    # Overall amendment risk score
    citations = []
    for finding in risk_result.top_findings:
        citations.append(
            SourceCitation(
                quote=finding.matched_text,
                page_number=finding.page_number,
                confidence_score=1.0,  # Rule-based, deterministic
                source_type=SourceType.TEXT,
            )
        )

    provenance["amendment_risk_score"] = ProvenanceRecord(
        metric_name="amendment_risk_score",
        value=risk_result.score,
        display_label="Amendment Risk Score",
        confidence_score=1.0,  # Deterministic rule-based score
        citations=citations,
        reasoning=(
            f"Evaluated {risk_result.rules_evaluated} amendment risk patterns. "
            f"{risk_result.rules_triggered} triggered. "
            f"Tier: {risk_result.tier} Risk."
        ),
    )

    # Individual findings as provenance
    for i, finding in enumerate(risk_result.top_findings):
        provenance[f"amendment_finding_{i}"] = ProvenanceRecord(
            metric_name=f"amendment_finding_{i}",
            value=finding.rule_id,
            display_label=f"Amendment Risk: {finding.pattern}",
            confidence_score=1.0,
            citations=[
                SourceCitation(
                    quote=finding.matched_text,
                    page_number=finding.page_number,
                    confidence_score=1.0,
                    source_type=SourceType.TEXT,
                )
            ],
            reasoning=finding.mitigation,
        )

    return provenance
