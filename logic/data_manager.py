import json
import pandas as pd

def load_data():
    #For this MVP, we will use the enhanced JSON data
    #The data is embedded directly in the code for simplicity but it belongs in data/synthetic_oncology.json

    data = [
        {
            "id": "ONC-001-PhaseIII",
             "name": "NSCLC Chemo-Immunotherapy Combo",
            "phase": "III",
            "therapeutic_area": "Oncology",
            "complexity_metrics": {
                "ie_criteria_count": 38,
                "endpoints_count": 12,
                "sites_count": 120,
                "amendments_predicted": 3
            },
            "patient_burden": {
                "total_visits": 24,
                "invasive_procedures": 4, # Biopsies
                "patient_reported_outcomes": 15, # QoL surveys
                "hospitalization_days": 2
            },
            "site_burden": {
                "staff_hours_per_patient": 145,
                "data_points_per_visit": 85,
                "sample_shipments": 12
            },
            "rwd_insights": [
                "ECOG 0 requirement excludes 42% of eligible population.",
                "Biopsy at Wk 6 has a 28% refusal rate historically."
            ]
        },
        {
            "id": "ONC-234-PhaseII",
            "name": "HER2+ Breast Cancer Targeted",
            "phase": "II",
            "therapeutic_area": "Oncology",
            "complexity_metrics": {
                "ie_criteria_count": 24,
                "endpoints_count": 6,
                "sites_count": 45,
                "amendments_predicted": 1
            },
            "patient_burden": {
                "total_visits": 14,
                "invasive_procedures": 2,
                "patient_reported_outcomes": 8,
                "hospitalization_days": 0
            },
            "site_burden": {
                "staff_hours_per_patient": 80,
                "data_points_per_visit": 40,
                "sample_shipments": 6
            },
            "rwd_insights": [
                "Prior line therapy limit excludes 18% of patients."
            ]
        },
        {
            "id": "HEM-009-PhaseI",
            "name": "Novel CAR-T for Multiple Myeloma",
            "phase": "I",
            "therapeutic_area": "Hematology",
            "complexity_metrics": {
                "ie_criteria_count": 18,
                "endpoints_count": 8,
                "sites_count": 5,
                "countries_count": 1
            },
            "patient_burden": {
                "total_visits": 45,
                "invasive_procedures": 6,
                "patient_reported_outcomes": 20,
                "hospitalization_days": 14
            },
            "site_burden": {
                "staff_hours_per_patient": 250,
                "data_points_per_visit": 120,
                "sample_shipments": 30
            },
            "rwd_insights": [
                "14-day hospitalization requirement limits site feasibility to major academic centers only."
            ]
        }
    ]
    return pd.DataFrame(data)

def get_protocol_details(df, protocol_id):
    return df[df['id'] == protocol_id].iloc[0]