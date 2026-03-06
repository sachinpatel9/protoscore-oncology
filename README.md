# ProtoScore Oncology: Clinical Trial Feasibility Engine

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Streamlit](https://img.shields.io/badge/Streamlit-1.30%2B-FF4B4B)
![Status](https://img.shields.io/badge/Status-MVP_Live-success)
![Focus](https://img.shields.io/badge/Domain-Oncology_Clinical_Ops-teal)

**ProtoScore** is a decision-support microservice that quantifies the operational complexity of oncology clinical trials. It empowers Clinical Operations teams to simulate protocol changes and evaluate site feasibility *before* a study is finalized.

---

## The Clinical Problem

Modern oncology protocols have reached a complexity tipping point. The drive for deeper scientific data has resulted in protocols with 40+ Inclusion/Exclusion criteria and dense Schedule of Assessment (SoA) tables. 

**The Business Impact:**
* **25%** of oncology trials fail to enroll their target populations due to restrictive criteria.
* Sites are burning out from excessive data-entry burdens.
* Clinical Ops lacks the quantitative data needed to negotiate operationally friendly designs with Medical Directors.

## The Solution

ProtoScore bridges the "Feasibility Gap." It shifts the paradigm from subjective protocol review to quantitative simulation. 

By ingesting key protocol metrics, ProtoScore calculates a **Protocol Complexity Score (PCS)** (0-100) based on three core pillars:
1. **Design Complexity:** Density of I/E criteria and study endpoints.
2. **Patient Burden:** Frequency of site visits and invasive procedures (e.g., biopsies).
3. **Site Burden:** Estimated staff hours per patient and CRF data volume.

---

## Architecture & Philosophy (Safety First)



In healthcare software, decision-support tools must be auditable and safe. 

**ProtoScore V1 deliberately avoids using Large Language Models (LLMs) for the scoring calculation.** Instead, the core engine relies on a **deterministic, weighted linear model** built with `NumPy` and `Pandas`. 

* **The Interface (Streamlit):** A reactive "Human-in-the-Loop" dashboard allowing users to toggle parameters (e.g., reducing required biopsies) to instantly simulate the impact on patient burden.
* **The Engine (Stateless API):** The scoring logic is completely decoupled from the UI. It operates as a stateless Python module, designed to be easily integrated into enterprise Clinical Trial Management Systems (CTMS) via REST API.

---

## Key Features

* **Interactive Radar Dashboards:** Visual breakdown of where a protocol's burden lies (Patient vs. Site vs. Design).
* **Real-time Optimization Simulator:** "What-if" analysis sliders that instantly recalculate the PCS to support trade-off discussions.
* **RWD Feasibility Alerts:** Flags specific criteria (e.g., "ECOG Status 0") that historically lead to high screen failure rates based on synthetic Real World Data.

---

## Local Installation & Usage

To run this tool locally on your machine:

**1. Clone the repository**
```bash
git clone https://github.com/sachinpatel9/protoscore-oncology.git
cd protoscore-oncology
