import numpy as np 

def calculate_pcs(protocol_data, weights):
    """
    Calculate the Protocol Complexity Score (PCS) based on dynamic weights.
    weights: dict -> {'complexity': 0.4, 'patient': 0.3, 'site': 0.3}

    """
    # 1. Normalize complexity features (mock logic for MVP)
    # In production, these max values would be dynamic based on the dataset however for MVP we will use static max values

    c_score = (
        (protocol_data['complexity_metrics']['ie_criteria_count'] / 50) * 0.5 +
        (protocol_data['complexity_metrics']['endpoints_count'] / 20) * 0.5) * 100
    
    # 2. Normalize Patient Burden features
    p_score = (
        (protocol_data['patient_burden']['total_visits'] / 30) * 0.4 +
        (protocol_data['patient_burden']['invasive_procedures'] / 6) * 0.6) * 100
    
    # 3. Normalize Site Burden features 
    s_score = (
            (protocol_data['site_burden']['staff_hours_per_patient'] / 200) * 0.5 +
            (protocol_data['site_burden']['data_points_per_visit'] / 150) * 0.5
        ) * 100
    # 4. Weighted sum to get final PCS
    final_score = (
        (c_score * weights['complexity']) + 
        (p_score * weights['patient']) + 
        (s_score * weights['site'])
    )
    return {
        "total": round(final_score, 2),
        "breakdown": {
            "Complexity": round(c_score, 2),
            "Patient Burden": round(p_score, 2),
            "Site Burden": round(s_score, 2)
        }
    }