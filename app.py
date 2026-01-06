import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from logic.data_manager import load_data, get_protocol_details
from logic.scoring import calculate_pcs

# --- Page Config ---
st.set_page_config(
    page_title="ProtoScore Oncology",
    layout="wide",
    initial_sidebar_state="expanded",
    page_icon="🧬"
)

# --- CSS Injection for "Vibe" ---
st.markdown("""
<style>
    .metric-card {
        background-color: #262730;
        padding: 20px;
        border-radius: 10px;
        border-left: 5px solid #00A3E0;
        margin-bottom: 20px;
    }
    .h1 { font-family: 'Helvetica Neue', sans-serif; font-weight: 800; }
</style>
""", unsafe_allow_html=True)

# --- Sidebar: Protocol Selection ---
st.sidebar.title("🧬 ProtoScore")
st.sidebar.markdown("Oncology Clinical Trial Assessment")
st.sidebar.divider()

data = load_data()
selected_protocol_id = st.sidebar.selectbox("Select Protocol Draft", data['id'])
current_protocol = get_protocol_details(data, selected_protocol_id)

st.sidebar.info(f"**Phase:** {current_protocol['phase']}\n\n**Therapeutic Area:** {current_protocol['therapeutic_area']}")

# --- Logic: Calculate Score ---
# Default Weights
default_weights = {'complexity': 0.4, 'patient': 0.3, 'site': 0.3}
score_result = calculate_pcs(current_protocol, default_weights)

# --- Main Layout ---

col1, col2 = st.columns([3, 1])

with col1:
    st.title(f"{current_protocol['name']}")
    st.markdown(f"**Protocol ID:** {current_protocol['id']}")

with col2:
    # The Hero Metric
    delta_color = "inverse" if score_result['total'] > 75 else "normal"
    st.metric(label="Complexity Score", value=score_result['total'], delta=f"{score_result['total']-50} vs Benchmark", delta_color=delta_color)

# --- Tabs for Interaction ---
tab1, tab2, tab3 = st.tabs(["📊 Assessment Dashboard", "🎛️ Optimization Simulator", "🤖 AI Recommendations"])

# === TAB 1: ASSESSMENT ===
with tab1:
    st.markdown("### Complexity Drivers Breakdown")
    
    # 3-Column Metrics
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"""
    <div class="metric-card">
        <h3>Design Complexity</h3>
        <h2>{score_result['breakdown']['Complexity']}</h2>
        <p>{current_protocol['complexity_metrics']['ie_criteria_count']} I/E Criteria</p>
    </div>
    """, unsafe_allow_html=True)
    
    c2.markdown(f"""
    <div class="metric-card">
        <h3>Patient Burden</h3>
        <h2>{score_result['breakdown']['Patient Burden']}</h2>
        <p>{current_protocol['patient_burden']['total_visits']} Visits / {current_protocol['patient_burden']['invasive_procedures']} Biopsies</p>
    </div>
    """, unsafe_allow_html=True)
    
    c3.markdown(f"""
    <div class="metric-card">
        <h3>Site Burden</h3>
        <h2>{score_result['breakdown']['Site Burden']}</h2>
        <p>{current_protocol['site_burden']['staff_hours_per_patient']} Staff Hours/Pt</p>
    </div>
    """, unsafe_allow_html=True)

    # Radar Chart
    st.markdown("### Multi-Dimensional Risk Analysis")
    categories = list(score_result['breakdown'].keys())
    values = list(score_result['breakdown'].values())
    
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values,
        theta=categories,
        fill='toself',
        name=current_protocol['name'],
        line_color='#00A3E0'
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=False,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color="white")
    )
    st.plotly_chart(fig, use_container_width=True)

# === TAB 2: SIMULATOR (The "Staff PM" Feature) ===
with tab2:
    st.markdown("### 🧪 What-If Analysis")
    st.markdown("Adjust protocol parameters to see impact on complexity and feasibility.")
    
    sim_col1, sim_col2 = st.columns(2)
    
    with sim_col1:
        st.markdown("**Design Adjustments**")
        new_biopsies = st.slider("Required Biopsies", 0, 6, int(current_protocol['patient_burden']['invasive_procedures']))
        new_visits = st.slider("Total Visits", 10, 40, int(current_protocol['patient_burden']['total_visits']))
        
    with sim_col2:
        # Real-time recalculation
        # Create a modified protocol object for calculation
        mod_protocol = current_protocol.copy()
        mod_protocol['patient_burden']['invasive_procedures'] = new_biopsies
        mod_protocol['patient_burden']['total_visits'] = new_visits
        
        new_score = calculate_pcs(mod_protocol, default_weights)
        
        st.metric(label="Simulated Score", value=new_score['total'], delta=round(new_score['total'] - score_result['total'], 1), delta_color="inverse")
        
        # Simple Bar Chart Comparison
        comp_df = pd.DataFrame({
            "Version": ["Current", "Simulated"],
            "Score": [score_result['total'], new_score['total']]
        })
        st.bar_chart(comp_df.set_index("Version"))

# === TAB 3: AI INSIGHTS ===
with tab3:
    st.markdown("### 🧬 RWD Feasibility Alerts")
    for insight in current_protocol['rwd_insights']:
        st.warning(f"⚠️ **Risk:** {insight}")
    
    st.markdown("### 💡 Optimization Opportunities")
    st.success("✅ **Recommendation:** Reducing biopsies from 4 to 2 (Optional in extension) would improve enrollment potential by estimated 15%.")