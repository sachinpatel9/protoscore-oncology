"""
Enrollment Rate Projector (Pillar E).

Converts the parsed I/E profile into a concrete enrollment rate estimate
(patients/site/month) using k-NN similarity matching against a benchmark
dataset of completed oncology trials.

Per FR 0.1: All calculations are deterministic Python. No LLM scoring.

FR-E6.1: Benchmark dataset integration (local CSV, trial-level aggregates only)
FR-E6.2: Profile matching via weighted similarity across multiple dimensions
FR-E6.3: Rate output with 80% CI, reference trials, top restrictive criteria
FR-E6.4: Time-to-full-enrollment estimate with sensitivity table
"""

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from logic.provenance import (
    ExtractionResult,
    ProvenanceRecord,
    SourceCitation,
    SourceType,
)

logger = logging.getLogger(__name__)

BENCHMARK_PATH = Path(__file__).resolve().parent.parent / "data" / "benchmark_trials.csv"

# Similarity dimension weights for profile matching
SIMILARITY_WEIGHTS = {
    "tumor_type": 0.30,
    "phase": 0.10,
    "ecog": 0.15,
    "prior_therapy": 0.15,
    "biomarker": 0.10,
    "ie_count": 0.10,
    "visits": 0.05,
    "invasive": 0.05,
}

# Population impact estimates for common restrictive criteria
POPULATION_IMPACT = {
    "ecog_0_only": {
        "criterion": "ECOG 0 only",
        "impact_pct": 40,
        "description": "Restricting to ECOG 0 excludes ~40% of standard oncology population",
    },
    "ecog_0_1": {
        "criterion": "ECOG 0-1",
        "impact_pct": 15,
        "description": "ECOG 0-1 excludes ~15% of patients with ECOG 2+",
    },
    "biomarker_pdl1": {
        "criterion": "PD-L1 biomarker selection",
        "impact_pct": 35,
        "description": "PD-L1 testing requirement narrows eligible pool by ~35%",
    },
    "biomarker_brca": {
        "criterion": "BRCA mutation required",
        "impact_pct": 75,
        "description": "BRCA requirement limits pool to ~10-25% of patients depending on tumor type",
    },
    "biomarker_msi": {
        "criterion": "MSI-H/dMMR selection",
        "impact_pct": 85,
        "description": "MSI-H prevalence is ~5-15% across solid tumors",
    },
    "prior_therapy_0": {
        "criterion": "Treatment-naive (0 prior lines)",
        "impact_pct": 30,
        "description": "First-line only excludes patients who have progressed on prior therapy",
    },
    "prior_therapy_3plus": {
        "criterion": "3+ prior therapy lines required",
        "impact_pct": 65,
        "description": "Requiring 3+ prior lines severely narrows the eligible population",
    },
    "high_biopsy": {
        "criterion": "Multiple biopsies (>3)",
        "impact_pct": 20,
        "description": "High biopsy burden increases screen failure rate by ~20%",
    },
}


@dataclass
class EnrollmentProjection:
    """Complete enrollment rate projection result."""
    rate_per_site_per_month: float
    confidence_interval_80: list[float]      # [lower, upper]
    reference_trials: list[dict]             # Top 3 most similar trials
    top_restrictive_criteria: list[dict]      # Criteria with highest enrollment impact
    similarity_scores: list[float] = field(default_factory=list)

    # Time-to-enrollment (populated when user provides inputs)
    estimated_months: float = 0.0
    sensitivity_table: list[dict] = field(default_factory=list)


def load_benchmark_data() -> pd.DataFrame:
    """Load the benchmark trials dataset."""
    try:
        df = pd.read_csv(BENCHMARK_PATH)
        return df
    except FileNotFoundError:
        logger.error(f"Benchmark dataset not found: {BENCHMARK_PATH}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Error loading benchmark data: {e}")
        return pd.DataFrame()


def _normalise_tumor_type(tumor_type: str) -> str:
    """Normalise tumor type strings for matching."""
    mapping = {
        "non-small cell lung": "NSCLC",
        "non small cell lung": "NSCLC",
        "nsclc": "NSCLC",
        "lung": "NSCLC",
        "breast": "Breast",
        "colorectal": "CRC",
        "colon": "CRC",
        "crc": "CRC",
        "melanoma": "Melanoma",
        "renal": "RCC",
        "kidney": "RCC",
        "rcc": "RCC",
        "gastric": "Gastric",
        "stomach": "Gastric",
        "gastroesophageal": "Gastric",
        "head and neck": "Head_Neck",
        "head_neck": "Head_Neck",
        "hnscc": "Head_Neck",
        "ovarian": "Ovarian",
        "pancreatic": "Pancreatic",
        "pancreas": "Pancreatic",
        "bladder": "Bladder",
        "urothelial": "Bladder",
        "hepatocellular": "Hepatocellular",
        "liver": "Hepatocellular",
        "hcc": "Hepatocellular",
        "prostate": "Prostate",
        "aml": "AML",
        "acute myeloid": "AML",
        "leukemia": "AML",
    }
    lower = tumor_type.lower().strip()
    for key, val in mapping.items():
        if key in lower:
            return val
    return tumor_type.strip()


def _extract_tumor_type(result: ExtractionResult) -> str:
    """Extract tumor type from protocol data."""
    area = result.protocol_data.get("therapeutic_area", "")
    indication = result.protocol_data.get("indication", "")
    combined = f"{area} {indication}".strip()
    if combined:
        return _normalise_tumor_type(combined)
    return "Unknown"


def _extract_phase(result: ExtractionResult) -> str:
    """Extract study phase."""
    return result.protocol_data.get("phase", "").strip()


def _extract_ecog_max(result: ExtractionResult) -> int:
    """Extract maximum ECOG from I/E criteria. Default to 1 if not found."""
    for crit in result.ie_criteria_detail:
        text = f"{crit.get('text', '')} {crit.get('source_quote', '')}".lower()
        if "ecog" in text:
            # Look for ECOG 0, ECOG 0-1, ECOG ≤1, etc.
            import re
            match = re.search(r'ecog.*?(\d)', text)
            if match:
                val = int(match.group(1))
                # If "ECOG 0" only, max is 0
                # If "ECOG 0-1" or "ECOG ≤1", max is 1
                range_match = re.search(r'ecog.*?(\d)\s*[-–]\s*(\d)', text)
                if range_match:
                    return int(range_match.group(2))
                le_match = re.search(r'ecog.*?[≤<]\s*(\d)', text)
                if le_match:
                    return int(le_match.group(1))
                return val
    return 1  # Default assumption


def _extract_prior_therapy_max(result: ExtractionResult) -> int:
    """Extract max prior therapy lines allowed."""
    import re
    for crit in result.ie_criteria_detail:
        text = f"{crit.get('text', '')} {crit.get('source_quote', '')}".lower()
        if any(kw in text for kw in ["prior", "previous", "line", "treatment-naive", "treatment naive", "first-line", "first line"]):
            if "naive" in text or "no prior" in text or "first-line" in text or "first line" in text:
                return 0
            match = re.search(r'(\d+)\s*(?:or fewer|or less|prior|previous)', text)
            if match:
                return int(match.group(1))
            match = re.search(r'[≤<]\s*(\d+)\s*(?:prior|previous|line)', text)
            if match:
                return int(match.group(1))
    return 1  # Default


def _extract_biomarker(result: ExtractionResult) -> str:
    """Extract biomarker requirement from I/E criteria."""
    biomarker_keywords = {
        "PD-L1": ["pd-l1", "pdl1", "pd-l 1"],
        "HER2": ["her2", "her-2", "erbb2"],
        "BRCA": ["brca", "brca1", "brca2"],
        "ALK": ["alk", "alk-positive", "alk rearrangement"],
        "EGFR": ["egfr", "egfr mutation"],
        "BRAF": ["braf", "braf v600"],
        "MSI-H": ["msi-h", "msi high", "dmmr", "microsatellite instab"],
        "KRAS": ["kras", "kras g12c"],
        "HR+HER2-": ["hr+", "hormone receptor positive", "hr-positive"],
        "FGFR": ["fgfr", "fgfr alteration"],
        "HRD": ["hrd", "homologous recombination"],
        "AFP": ["afp", "alpha-fetoprotein"],
    }

    for crit in result.ie_criteria_detail:
        text = f"{crit.get('text', '')} {crit.get('source_quote', '')}".lower()
        for biomarker, keywords in biomarker_keywords.items():
            if any(kw in text for kw in keywords):
                return biomarker
    return "None"


def _compute_similarity(
    protocol_profile: dict,
    trial_row: pd.Series,
) -> float:
    """
    Compute weighted similarity between protocol profile and a benchmark trial.

    Returns a similarity score between 0.0 and 1.0.
    """
    scores = {}

    # Tumor type match (exact = 1.0, same category = 0.5, different = 0.0)
    prot_tumor = _normalise_tumor_type(protocol_profile["tumor_type"])
    trial_tumor = trial_row.get("tumor_type", "")
    if prot_tumor == trial_tumor:
        scores["tumor_type"] = 1.0
    elif prot_tumor == "Unknown":
        scores["tumor_type"] = 0.3  # Partial credit for unknown
    else:
        scores["tumor_type"] = 0.0

    # Phase match
    prot_phase = protocol_profile.get("phase", "")
    trial_phase = str(trial_row.get("phase", ""))
    if prot_phase == trial_phase:
        scores["phase"] = 1.0
    elif prot_phase in trial_phase or trial_phase in prot_phase:
        scores["phase"] = 0.5
    else:
        scores["phase"] = 0.2

    # ECOG similarity (closer = more similar)
    prot_ecog = protocol_profile.get("ecog_max", 1)
    trial_ecog = trial_row.get("ecog_max", 1)
    ecog_diff = abs(prot_ecog - trial_ecog)
    scores["ecog"] = max(0.0, 1.0 - ecog_diff * 0.5)

    # Prior therapy lines similarity
    prot_prior = protocol_profile.get("prior_therapy_max", 1)
    trial_prior = trial_row.get("prior_therapy_lines_max", 1)
    prior_diff = abs(prot_prior - trial_prior)
    scores["prior_therapy"] = max(0.0, 1.0 - prior_diff * 0.3)

    # Biomarker match
    prot_bio = protocol_profile.get("biomarker", "None")
    trial_bio = trial_row.get("biomarker_required", "None")
    if prot_bio == trial_bio:
        scores["biomarker"] = 1.0
    elif prot_bio == "None" and trial_bio == "None":
        scores["biomarker"] = 1.0
    elif prot_bio == "None" or trial_bio == "None":
        scores["biomarker"] = 0.4
    else:
        scores["biomarker"] = 0.1

    # I/E criteria count similarity (normalised distance)
    prot_ie = protocol_profile.get("ie_count", 20)
    trial_ie = trial_row.get("ie_criteria_count", 20)
    ie_diff = abs(prot_ie - trial_ie)
    scores["ie_count"] = max(0.0, 1.0 - ie_diff / 30.0)

    # Visit count similarity
    prot_visits = protocol_profile.get("total_visits", 16)
    trial_visits = trial_row.get("total_visits", 16)
    visit_diff = abs(prot_visits - trial_visits)
    scores["visits"] = max(0.0, 1.0 - visit_diff / 20.0)

    # Invasive procedures similarity
    prot_inv = protocol_profile.get("invasive_procedures", 2)
    trial_inv = trial_row.get("invasive_procedures", 2)
    inv_diff = abs(prot_inv - trial_inv)
    scores["invasive"] = max(0.0, 1.0 - inv_diff / 5.0)

    # Weighted sum
    total = sum(
        scores.get(dim, 0.0) * weight
        for dim, weight in SIMILARITY_WEIGHTS.items()
    )
    return round(total, 4)


def _identify_restrictive_criteria(protocol_profile: dict) -> list[dict]:
    """Identify the most restrictive criteria affecting enrollment."""
    restrictive = []

    ecog = protocol_profile.get("ecog_max", 1)
    if ecog == 0:
        info = POPULATION_IMPACT["ecog_0_only"]
        restrictive.append({
            "criterion": info["criterion"],
            "estimated_pool_impact": f"+{info['impact_pct']}%",
            "description": info["description"],
        })
    elif ecog == 1:
        info = POPULATION_IMPACT["ecog_0_1"]
        restrictive.append({
            "criterion": info["criterion"],
            "estimated_pool_impact": f"+{info['impact_pct']}%",
            "description": info["description"],
        })

    biomarker = protocol_profile.get("biomarker", "None")
    bio_key = {
        "PD-L1": "biomarker_pdl1",
        "BRCA": "biomarker_brca",
        "MSI-H": "biomarker_msi",
    }.get(biomarker)
    if bio_key:
        info = POPULATION_IMPACT[bio_key]
        restrictive.append({
            "criterion": info["criterion"],
            "estimated_pool_impact": f"+{info['impact_pct']}%",
            "description": info["description"],
        })

    prior = protocol_profile.get("prior_therapy_max", 1)
    if prior == 0:
        info = POPULATION_IMPACT["prior_therapy_0"]
        restrictive.append({
            "criterion": info["criterion"],
            "estimated_pool_impact": f"+{info['impact_pct']}%",
            "description": info["description"],
        })
    elif prior >= 3:
        info = POPULATION_IMPACT["prior_therapy_3plus"]
        restrictive.append({
            "criterion": info["criterion"],
            "estimated_pool_impact": f"+{info['impact_pct']}%",
            "description": info["description"],
        })

    invasive = protocol_profile.get("invasive_procedures", 2)
    if invasive > 3:
        info = POPULATION_IMPACT["high_biopsy"]
        restrictive.append({
            "criterion": info["criterion"],
            "estimated_pool_impact": f"+{info['impact_pct']}%",
            "description": info["description"],
        })

    # Sort by impact percentage descending
    restrictive.sort(
        key=lambda x: int(x["estimated_pool_impact"].strip("+%")),
        reverse=True,
    )
    return restrictive[:3]


def _build_sensitivity_table(
    rate: float,
    num_sites: int,
    target_n: int,
) -> list[dict]:
    """
    Build sensitivity table showing impact of ±20% rate variance.

    FR-E6.4: Sensitivity table with rate variance scenarios.
    """
    scenarios = [
        {"label": "Pessimistic (-20%)", "multiplier": 0.8},
        {"label": "Base Case", "multiplier": 1.0},
        {"label": "Optimistic (+20%)", "multiplier": 1.2},
    ]

    table = []
    for scenario in scenarios:
        adjusted_rate = rate * scenario["multiplier"]
        if adjusted_rate > 0 and num_sites > 0:
            months = target_n / (adjusted_rate * num_sites)
        else:
            months = float("inf")
        table.append({
            "scenario": scenario["label"],
            "rate": round(adjusted_rate, 2),
            "months": round(months, 1) if months != float("inf") else "N/A",
        })
    return table


def project_enrollment(
    result: ExtractionResult,
    num_sites: int = 0,
    target_n: int = 0,
) -> EnrollmentProjection:
    """
    Project enrollment rate for a protocol based on k-NN similarity matching.

    Args:
        result: ExtractionResult from the extraction pipeline
        num_sites: Number of planned sites (for time-to-enrollment calc)
        target_n: Target enrollment count (for time-to-enrollment calc)

    Returns:
        EnrollmentProjection with rate, CI, reference trials, and restrictive criteria
    """
    benchmark = load_benchmark_data()
    if benchmark.empty:
        return EnrollmentProjection(
            rate_per_site_per_month=0.0,
            confidence_interval_80=[0.0, 0.0],
            reference_trials=[],
            top_restrictive_criteria=[],
        )

    # Build protocol profile from extraction result
    profile = {
        "tumor_type": _extract_tumor_type(result),
        "phase": _extract_phase(result),
        "ecog_max": _extract_ecog_max(result),
        "prior_therapy_max": _extract_prior_therapy_max(result),
        "biomarker": _extract_biomarker(result),
        "ie_count": result.protocol_data.get("complexity_metrics", {}).get("ie_criteria_count", 20),
        "total_visits": result.protocol_data.get("patient_burden", {}).get("total_visits", 16),
        "invasive_procedures": result.protocol_data.get("patient_burden", {}).get("invasive_procedures", 2),
    }

    # Compute similarity to each benchmark trial
    similarities = []
    for idx, row in benchmark.iterrows():
        sim = _compute_similarity(profile, row)
        similarities.append((idx, sim, row))

    # Sort by similarity descending
    similarities.sort(key=lambda x: x[1], reverse=True)

    # k-NN: use top K most similar trials
    K = min(5, len(similarities))
    top_k = similarities[:K]

    # Weighted average enrollment rate (weighted by similarity)
    total_weight = sum(sim for _, sim, _ in top_k)
    if total_weight > 0:
        weighted_rate = sum(
            sim * row["enrollment_rate_per_site_month"]
            for _, sim, row in top_k
        ) / total_weight
    else:
        weighted_rate = 1.5  # Default fallback

    # 80% confidence interval from the k-NN neighbors
    rates = [row["enrollment_rate_per_site_month"] for _, _, row in top_k]
    if len(rates) >= 2:
        rates_arr = np.array(rates)
        ci_lower = float(np.percentile(rates_arr, 10))
        ci_upper = float(np.percentile(rates_arr, 90))
    else:
        ci_lower = weighted_rate * 0.7
        ci_upper = weighted_rate * 1.3

    # Top 3 reference trials
    reference_trials = []
    for idx, sim, row in top_k[:3]:
        reference_trials.append({
            "nct_id": row["nct_id"],
            "tumor_type": row["tumor_type"],
            "phase": str(row["phase"]),
            "enrollment_rate": row["enrollment_rate_per_site_month"],
            "similarity": round(sim, 2),
            "total_enrolled": int(row["total_enrolled"]),
            "num_sites": int(row["num_sites"]),
        })

    # Identify restrictive criteria
    restrictive = _identify_restrictive_criteria(profile)

    # Time-to-enrollment estimate (FR-E6.4)
    estimated_months = 0.0
    sensitivity = []
    if num_sites > 0 and target_n > 0:
        estimated_months = target_n / (weighted_rate * num_sites)
        sensitivity = _build_sensitivity_table(weighted_rate, num_sites, target_n)

    return EnrollmentProjection(
        rate_per_site_per_month=round(weighted_rate, 2),
        confidence_interval_80=[round(ci_lower, 2), round(ci_upper, 2)],
        reference_trials=reference_trials,
        top_restrictive_criteria=restrictive,
        similarity_scores=[sim for _, sim, _ in top_k],
        estimated_months=round(estimated_months, 1),
        sensitivity_table=sensitivity,
    )


def build_enrollment_provenance(
    projection: EnrollmentProjection,
) -> dict[str, ProvenanceRecord]:
    """
    Build provenance records for enrollment projection.

    Returns dict of ProvenanceRecord keyed by metric name.
    """
    provenance = {}

    # Reference trial citations
    citations = []
    for ref in projection.reference_trials:
        citations.append(
            SourceCitation(
                quote=f"{ref['nct_id']} ({ref['tumor_type']} Phase {ref['phase']}) — "
                      f"{ref['enrollment_rate']} pts/site/mo, similarity {ref['similarity']}",
                page_number=0,
                confidence_score=ref["similarity"],
                source_type=SourceType.INFERRED,
            )
        )

    provenance["enrollment_rate"] = ProvenanceRecord(
        metric_name="enrollment_rate",
        value=projection.rate_per_site_per_month,
        display_label="Enrollment Rate (pts/site/month)",
        confidence_score=max(projection.similarity_scores) if projection.similarity_scores else 0.5,
        citations=citations,
        reasoning=(
            f"Projected {projection.rate_per_site_per_month} pts/site/month "
            f"(80% CI: [{projection.confidence_interval_80[0]}, {projection.confidence_interval_80[1]}]) "
            f"based on {len(projection.reference_trials)} similar completed trials."
        ),
    )

    return provenance
