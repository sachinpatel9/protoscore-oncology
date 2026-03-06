"""
Data manager for ProtoScore V2.

Provides demo protocol data with drastically varied complexity levels,
and bridges between AI extraction results and the scoring engine.
"""

import pandas as pd
from logic.provenance import ExtractionResult


def load_demo_data() -> pd.DataFrame:
    """
    Load 3 demo protocols with drastically different complexity levels.

    LOW  (~25-30 PCS): Simple Phase II adjuvant trial
    MED  (~50-55 PCS): Typical Phase II/III combo immunotherapy
    HIGH (~85-90 PCS): Complex Phase I/II multi-arm basket trial

    Returns:
        DataFrame with one row per protocol
    """
    data = [
        # ---------------------------------------------------------------
        # LOW COMPLEXITY: Simple, clean, investigator-friendly trial
        # ---------------------------------------------------------------
        {
            "id": "ONC-112-PhaseII",
            "name": "HER2+ Early Breast Cancer Adjuvant Monotherapy",
            "phase": "II",
            "therapeutic_area": "Oncology - Breast",
            "study_design": "Single-arm, open-label adjuvant monotherapy",
            "complexity_metrics": {
                "ie_criteria_count": 12,
                "endpoints_count": 4,
                "sites_count": 25,
                "amendments_predicted": 0,
            },
            "patient_burden": {
                "total_visits": 8,
                "invasive_procedures": 1,
                "patient_reported_outcomes": 4,
                "hospitalization_days": 0,
            },
            "site_burden": {
                "staff_hours_per_patient": 40,
                "data_points_per_visit": 25,
                "sample_shipments": 3,
            },
            "amendment_risk": {
                "score": 12,
                "tier": "Low",
                "rules_evaluated": 8,
                "rules_triggered": 0,
                "top_findings": [],
            },
            "enrollment_projection": {
                "rate_per_site_per_month": 3.2,
                "confidence_interval_80": [2.5, 4.0],
                "reference_trials": [
                    {"nct_id": "NCT03516981", "tumor_type": "Breast", "phase": "III", "enrollment_rate": 3.2, "similarity": 0.82, "total_enrolled": 480, "num_sites": 120},
                    {"nct_id": "NCT03125902", "tumor_type": "Breast", "phase": "II", "enrollment_rate": 2.5, "similarity": 0.76, "total_enrolled": 225, "num_sites": 60},
                    {"nct_id": "NCT02614794", "tumor_type": "Breast", "phase": "III", "enrollment_rate": 2.1, "similarity": 0.68, "total_enrolled": 672, "num_sites": 160},
                ],
                "top_restrictive_criteria": [],
            },
            "procedure_weight_summary": {
                "total_patient_minutes": 385,
                "mapped_count": 5,
                "unmapped_count": 0,
                "coverage_pct": 100.0,
                "top_procedures": [
                    {"procedure": "Study Drug Administration (IV infusion)", "category": "Treatment", "minutes": 180, "count": 1},
                    {"procedure": "Blood Draw (Routine labs)", "category": "Biospecimen", "minutes": 120, "count": 8},
                    {"procedure": "Physical Examination", "category": "Clinical Assessment", "minutes": 40, "count": 2},
                ],
            },
            "burden_spikes": [],
            "population_impacts": [],
            "sequencing_risks": [],
            "rwd_insights": [
                "Broad eligibility: No ECOG restriction beyond ≤2, captures ~90% of target population.",
                "Minimal invasive burden: Single baseline biopsy with optional archival tissue accepted.",
            ],
        },
        # ---------------------------------------------------------------
        # MEDIUM COMPLEXITY: Typical pivotal trial
        # ---------------------------------------------------------------
        {
            "id": "ONC-301-PhaseIII",
            "name": "NSCLC First-Line Chemo-Immunotherapy Combination",
            "phase": "III",
            "therapeutic_area": "Oncology - Lung",
            "study_design": "Randomized, double-blind, placebo-controlled, 2-arm",
            "complexity_metrics": {
                "ie_criteria_count": 26,
                "endpoints_count": 9,
                "sites_count": 85,
                "amendments_predicted": 2,
            },
            "patient_burden": {
                "total_visits": 18,
                "invasive_procedures": 3,
                "patient_reported_outcomes": 10,
                "hospitalization_days": 1,
            },
            "site_burden": {
                "staff_hours_per_patient": 110,
                "data_points_per_visit": 65,
                "sample_shipments": 10,
            },
            "amendment_risk": {
                "score": 52,
                "tier": "Moderate",
                "rules_evaluated": 8,
                "rules_triggered": 3,
                "top_findings": [
                    {
                        "rule_id": "AMR-04",
                        "pattern": "Response assessment window < 6 weeks in IO trial",
                        "weight": 0.80,
                        "occurrences": 1,
                        "matched_text": "Tumor assessment every 6 weeks per RECIST 1.1 with pembrolizumab",
                        "page_number": 0,
                        "common_amendment": "Extend assessment window to 8-12 weeks to accommodate delayed IO response",
                        "mitigation": "Extend response assessment window to 8-12 weeks to accommodate delayed immune-mediated responses (pseudoprogression).",
                    },
                    {
                        "rule_id": "AMR-05",
                        "pattern": "Ambiguous language without numeric threshold in exclusion criterion",
                        "weight": 0.60,
                        "occurrences": 2,
                        "matched_text": "No clinically significant cardiac disease",
                        "page_number": 0,
                        "common_amendment": "Add numeric threshold (e.g., 'ALT > 3x ULN') to prevent inconsistent screening",
                        "mitigation": "Replace ambiguous language with specific numeric thresholds to ensure consistent screening across sites.",
                    },
                    {
                        "rule_id": "AMR-08",
                        "pattern": "Double-blind design without sham procedure detail",
                        "weight": 0.55,
                        "occurrences": 1,
                        "matched_text": "Randomized, double-blind, placebo-controlled IV infusion",
                        "page_number": 0,
                        "common_amendment": "Add sham procedure protocol to maintain blind integrity",
                        "mitigation": "Define a sham procedure protocol (e.g., matching IV infusion) to maintain blinding integrity for the non-oral route of administration.",
                    },
                ],
            },
            "enrollment_projection": {
                "rate_per_site_per_month": 1.8,
                "confidence_interval_80": [1.2, 2.4],
                "reference_trials": [
                    {"nct_id": "NCT02813785", "tumor_type": "NSCLC", "phase": "III", "enrollment_rate": 1.8, "similarity": 0.88, "total_enrolled": 616, "num_sites": 180},
                    {"nct_id": "NCT02578680", "tumor_type": "NSCLC", "phase": "III", "enrollment_rate": 1.5, "similarity": 0.85, "total_enrolled": 559, "num_sites": 220},
                    {"nct_id": "NCT03215810", "tumor_type": "NSCLC", "phase": "III", "enrollment_rate": 2.4, "similarity": 0.72, "total_enrolled": 723, "num_sites": 200},
                ],
                "top_restrictive_criteria": [
                    {"criterion": "PD-L1 biomarker selection", "estimated_pool_impact": "+35%", "description": "PD-L1 testing requirement narrows eligible pool by ~35%"},
                    {"criterion": "ECOG 0-1", "estimated_pool_impact": "+15%", "description": "ECOG 0-1 excludes ~15% of patients with ECOG 2+"},
                ],
            },
            "procedure_weight_summary": {
                "total_patient_minutes": 1455,
                "mapped_count": 10,
                "unmapped_count": 1,
                "coverage_pct": 90.9,
                "top_procedures": [
                    {"procedure": "Study Drug Administration (IV infusion)", "category": "Treatment", "minutes": 540, "count": 3},
                    {"procedure": "CT Scan", "category": "Imaging", "minutes": 360, "count": 6},
                    {"procedure": "Blood Draw (Routine labs)", "category": "Biospecimen", "minutes": 270, "count": 18},
                ],
            },
            "burden_spikes": [
                {
                    "visit_name": "Cycle 1 Day 1",
                    "total_hours": 5.2,
                    "invasive_count": 3,
                    "procedures": ["Blood Draw", "Tumor Biopsy", "IV Infusion", "ECG", "Vital Signs"],
                    "reason": "both",
                },
            ],
            "population_impacts": [
                {
                    "criterion_text": "PD-L1 TPS ≥1% by IHC",
                    "impact_key": "pdl1_required",
                    "impact_pct": 35,
                    "description": "PD-L1 selection — narrows eligible pool by ~35%",
                    "suggestion": "Consider enrolling all-comers with PD-L1 stratification.",
                    "page_number": 0,
                },
                {
                    "criterion_text": "ECOG Performance Status 0-1",
                    "impact_key": "ecog_0_1",
                    "impact_pct": 15,
                    "description": "ECOG 0-1 — excludes ~15% of patients (ECOG 2+)",
                    "suggestion": None,
                    "page_number": 0,
                },
            ],
            "sequencing_risks": [],
            "rwd_insights": [
                "ECOG 0-1 requirement excludes ~35% of real-world NSCLC patients.",
                "On-treatment biopsy at Week 9 has historically shown ~22% refusal rate.",
                "PD-L1 TPS ≥1% enrichment narrows eligible population by ~40%.",
            ],
        },
        # ---------------------------------------------------------------
        # HIGH COMPLEXITY: Resource-intensive multi-arm trial
        # ---------------------------------------------------------------
        {
            "id": "HEM-045-PhaseI/II",
            "name": "CAR-T Plus Bispecific Antibody Combination in R/R AML",
            "phase": "I/II",
            "therapeutic_area": "Hematology - Acute Myeloid Leukemia",
            "study_design": "Dose-escalation + expansion, multi-arm basket with 4 cohorts",
            "complexity_metrics": {
                "ie_criteria_count": 42,
                "endpoints_count": 14,
                "sites_count": 8,
                "amendments_predicted": 4,
            },
            "patient_burden": {
                "total_visits": 34,
                "invasive_procedures": 6,
                "patient_reported_outcomes": 22,
                "hospitalization_days": 14,
            },
            "site_burden": {
                "staff_hours_per_patient": 220,
                "data_points_per_visit": 130,
                "sample_shipments": 28,
            },
            "amendment_risk": {
                "score": 78,
                "tier": "High",
                "rules_evaluated": 8,
                "rules_triggered": 5,
                "top_findings": [
                    {
                        "rule_id": "AMR-01",
                        "pattern": "ECOG 0 only in solid tumour indication",
                        "weight": 0.70,
                        "occurrences": 1,
                        "matched_text": "ECOG Performance Status 0",
                        "page_number": 0,
                        "common_amendment": "Expand to ECOG 0-1 post-activation due to slow enrollment",
                        "mitigation": "Consider expanding eligibility to ECOG 0-1 to increase the recruitable patient pool by ~40%.",
                    },
                    {
                        "rule_id": "AMR-02",
                        "pattern": "Biopsy count > 3 total",
                        "weight": 0.60,
                        "occurrences": 1,
                        "matched_text": "6 bone marrow biopsies required over 12 months",
                        "page_number": 0,
                        "common_amendment": "Remove or make optional one biopsy to reduce screen fail",
                        "mitigation": "Consider making at least one biopsy optional (e.g., 'if accessible') to reduce screen failure rates.",
                    },
                    {
                        "rule_id": "AMR-05",
                        "pattern": "Ambiguous language without numeric threshold in exclusion criterion",
                        "weight": 0.60,
                        "occurrences": 3,
                        "matched_text": "No clinically significant organ dysfunction",
                        "page_number": 0,
                        "common_amendment": "Add numeric threshold (e.g., 'ALT > 3x ULN') to prevent inconsistent screening",
                        "mitigation": "Replace ambiguous language with specific numeric thresholds to ensure consistent screening across sites.",
                    },
                ],
            },
            "enrollment_projection": {
                "rate_per_site_per_month": 0.4,
                "confidence_interval_80": [0.3, 0.6],
                "reference_trials": [
                    {"nct_id": "NCT04150029", "tumor_type": "AML", "phase": "I/II", "enrollment_rate": 0.4, "similarity": 0.91, "total_enrolled": 48, "num_sites": 25},
                    {"nct_id": "NCT03170947", "tumor_type": "AML", "phase": "I/II", "enrollment_rate": 0.5, "similarity": 0.84, "total_enrolled": 64, "num_sites": 30},
                ],
                "top_restrictive_criteria": [
                    {"criterion": "ECOG 0 only", "estimated_pool_impact": "+40%", "description": "Restricting to ECOG 0 excludes ~40% of standard oncology population"},
                    {"criterion": "Multiple biopsies (>3)", "estimated_pool_impact": "+20%", "description": "High biopsy burden increases screen failure rate by ~20%"},
                    {"criterion": "3+ prior therapy lines required", "estimated_pool_impact": "+65%", "description": "Requiring 3+ prior lines severely narrows the eligible population"},
                ],
            },
            "procedure_weight_summary": {
                "total_patient_minutes": 4290,
                "mapped_count": 14,
                "unmapped_count": 2,
                "coverage_pct": 87.5,
                "top_procedures": [
                    {"procedure": "Bone Marrow Biopsy", "category": "Biospecimen", "minutes": 720, "count": 6},
                    {"procedure": "Study Drug Administration (IV infusion)", "category": "Treatment", "minutes": 540, "count": 3},
                    {"procedure": "Blood Draw (Routine labs)", "category": "Biospecimen", "minutes": 510, "count": 34},
                ],
            },
            "burden_spikes": [
                {
                    "visit_name": "Screening Visit",
                    "total_hours": 6.5,
                    "invasive_count": 4,
                    "procedures": ["Bone Marrow Biopsy", "Blood Draw", "Lumbar Puncture", "ECG", "Echo", "PFT"],
                    "reason": "both",
                },
                {
                    "visit_name": "Cycle 1 Day 1",
                    "total_hours": 7.0,
                    "invasive_count": 3,
                    "procedures": ["Leukapheresis", "Blood Draw", "PK Blood Draw", "Vital Signs"],
                    "reason": "both",
                },
                {
                    "visit_name": "Day 28 (Post-Infusion)",
                    "total_hours": 4.5,
                    "invasive_count": 3,
                    "procedures": ["Bone Marrow Biopsy", "Blood Draw", "PK Blood Draw", "Physical Exam"],
                    "reason": "both",
                },
            ],
            "population_impacts": [
                {
                    "criterion_text": "≥3 prior lines of therapy for AML",
                    "impact_key": "prior_therapy_3plus",
                    "impact_pct": 60,
                    "description": "3+ prior lines — excludes ~60% of the general oncology population",
                    "suggestion": None,
                    "page_number": 0,
                },
                {
                    "criterion_text": "ECOG Performance Status 0",
                    "impact_key": "ecog_0",
                    "impact_pct": 40,
                    "description": "ECOG 0 only — excludes ~40% of standard oncology SOC population",
                    "suggestion": "Consider expanding to ECOG 0-1 to improve enrollment rate.",
                    "page_number": 0,
                },
            ],
            "sequencing_risks": [
                {
                    "procedure_a": "Bone Marrow Biopsy",
                    "procedure_b": "Lumbar Puncture",
                    "gap_days": 0,
                    "risk_description": "Bone Marrow Biopsy and Lumbar Puncture are scheduled within 0 days — compounded invasive burden.",
                    "page_number": 0,
                },
                {
                    "procedure_a": "Bone Marrow Biopsy",
                    "procedure_b": "PK Blood Draw",
                    "gap_days": 7,
                    "risk_description": "Bone Marrow Biopsy and PK Blood Draw are scheduled within 7 days — compounded patient burden.",
                    "page_number": 0,
                },
            ],
            "rwd_insights": [
                "14-day mandatory hospitalization limits feasibility to major academic centers only.",
                "6 bone marrow biopsies over 12 months: historical dropout rate ~30% by 4th biopsy.",
                "ECOG 0 requirement excludes ~55% of R/R AML population.",
                "Leukapheresis + lymphodepletion + CAR-T infusion sequence creates 3-week patient commitment window.",
                "CNS assessment with lumbar puncture at screening deters ~15% of otherwise eligible patients.",
            ],
        },
    ]
    return pd.DataFrame(data)


# Backward compatibility alias
load_data = load_demo_data


def load_from_extraction(extraction_result: ExtractionResult) -> pd.DataFrame:
    """
    Convert an ExtractionResult into the DataFrame format expected by the app.

    Args:
        extraction_result: Output from the AI extraction pipeline

    Returns:
        Single-row DataFrame in the same shape as load_demo_data()
    """
    protocol_data = extraction_result.protocol_data.copy()
    protocol_data["id"] = protocol_data.get("id", f"UPLOADED-{extraction_result.source_filename}")
    protocol_data["name"] = protocol_data.get("name", extraction_result.source_filename or "Uploaded Protocol")
    return pd.DataFrame([protocol_data])


def get_protocol_details(df: pd.DataFrame, protocol_id: str):
    """Retrieve a single protocol row by ID."""
    return df[df["id"] == protocol_id].iloc[0]
