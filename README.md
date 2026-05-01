# ProtoScore Oncology: Clinical Trial Feasibility Engine

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Gradio](https://img.shields.io/badge/Gradio-5.x-FF4B4B)
![Pandas](https://img.shields.io/badge/Pandas-2.x-yellow)
![Status](https://img.shields.io/badge/Version-2.1-green)
![Focus](https://img.shields.io/badge/Domain-Oncology_Clinical_Ops-teal)

## The Cognitive Feasibility Engine

ProtoScore Oncology is an AI-powered clinical trial analyst designed to quantify the operational complexity of oncology protocols. By evolving from a simple calculator to an autonomous agentic system, ProtoScore demystifies the clinical trial decision-making process, replacing "gut-feel" with evidence-based quantification of patient and site burden.

---

## The Clinical Problem

Clinical trial design is currently a high-stakes, manual process. In industry settings, feasibility decisions are often made by medical directors based on subjective experience rather than empirical data. This lack of quantification leads to significant operational risks:

* **Table Blindness**: Standard RAG architectures struggle to parse the Schedule of Assessment (SoA) tables where the highest operational costs are hidden.
* **Linear Misinterpretation**: A "biopsy" listed in eligibility criteria carries a different operational weight than a mandatory "biopsy" in a treatment cycle; standard tools treat these as identical text strings.
* **Informative Censoring**: Onerous protocol designs lead to early patient withdrawal, introducing statistical bias that can invalidate survival analyses.

## The Solution

ProtoScore V2 shifts the paradigm from subjective review to **Quantitative Simulation**. It acts as an analyst that reads raw protocol PDFs, recognizes the structural nuances of clinical documents, and extracts metrics autonomously to calculate a **Protocol Complexity Score (PCS)** — a deterministic 0-100 score backed by a transparent formula and click-to-verify provenance.

---

## Key Features — The Five Pillars

ProtoScore V2.1 organizes its analysis into five complementary pillars. Each produces an auditable sub-score that rolls up into the overall PCS, and every extracted value is linked to the exact quote, page number, and confidence score in the source document.

### Pillar A — Site Feasibility
Layout-aware parsing of the Schedule of Assessment table converts 2-D visit grids into structured dataframes. Staff hours, data points per visit, and procedure counts are extracted directly from the SoA rather than approximated from prose. This makes the operational footprint at each site measurable and comparable across protocols. The output drives the Site Burden sub-score and is shown in the scorecard with a per-visit breakdown.

### Pillar B — Patient Recruitment
Inclusion and exclusion criteria are parsed into boolean logic trees rather than treated as bag-of-text. The pipeline identifies "blocker clauses" — criteria whose strict thresholds disproportionately compress the eligible population — and surfaces them as recruitment risk drivers. Counts feed the Complexity sub-score, while the structured representation enables the Criteria Relaxation Simulator. Each criterion stays linked to its source paragraph for clinician review.

### Pillar C — Biospecimen Feasibility
Invasive procedures (biopsies, bone marrow aspirates, lumbar punctures) are mapped across the trial timeline, not just counted. The Temporal Agent identifies "burden spikes" — weeks where multiple invasive procedures cluster — that are statistically associated with patient dropout. This produces a per-week burden curve in addition to the headline Patient Burden sub-score. The visualization makes it immediately obvious where to negotiate with the sponsor.

### Pillar D — Amendment Risk Score
Protocol amendments are expensive and often predictable from the original draft. The Amendment Risk Score combines features known to correlate with mid-trial amendments (criteria over-specification, endpoint count, procedural density) into a forward-looking probability estimate. The score is presented alongside the formula so the relative weight of each driver is transparent. Sponsors can use this to prioritize design changes before the first site is activated.

### Pillar E — Enrollment Rate Projector
The Enrollment Rate Projector estimates patients per site per month with an 80% confidence interval, using the protocol's own complexity profile. The Optimization Simulator's Enrollment Timeline Calculator then translates that rate into a time-to-full-enrollment estimate for any combination of site count and target N. A sensitivity table shows pessimistic, base-case, and optimistic scenarios. This closes the loop from "how complex is this protocol?" to "how long will it actually take to enroll?"

---

## Enterprise Architecture

To meet the security and transparency requirements of pharmaceutical R&D, ProtoScore V2 is built on a decoupled, enterprise-grade stack.

### Model-Agnostic Backend

Designed for strict data governance, the backend uses a router-based architecture that allows users to toggle between three inference engines at runtime:

* **OpenAI (Cloud)** — high-reasoning frontier models via the OpenAI API for public or non-sensitive protocols.
* **Claude (Cloud)** — Anthropic's frontier models via the Anthropic API, used through structured `tool_use` calls for the same JSON feature vector contract.
* **Ollama (Local)** — secure, on-premise deployment via local LLMs (e.g., Llama 3.1) for highly sensitive Phase I pipeline assets, ensuring **zero data exfiltration**. No API key required.

All three providers are routed through a single `Provider` enum and a `BaseExtractionPipeline` ABC that share one `TOOL_SCHEMAS` definition, so the scoring engine cannot tell which provider produced an extraction — guaranteeing schema parity across cloud and local deployments.

### Explainable AI (XAI)

Clinician trust is built through transparency. Every score generated by ProtoScore includes a **Click-to-Verify** audit trail:

* Each extracted value is linked to a specific citation containing the exact quote, page number, and confidence score.
* The UI features a split-screen view where clicking a metric automatically scrolls and highlights the evidence within the source PDF (bidirectional navigation).
* A **Batch Verification** tab presents all extracted fields in a single review table with confidence bars, source quotes, and inline PDF thumbnails. Per-row HITL approval is the gate: every extraction row lands as `Pending`, reviewers optionally edit any numeric score-driver field and click `✓ Approve Update` per row, and `Confirm & Score` is blocked until no pending rows remain. The full audit log is exportable as JSON for regulatory submissions.
* PII (SSN, phone, email, MRN) is regex-scrubbed before any text reaches an LLM.

### Technical Stack

* **Frontend**: Gradio (split-screen layout, custom CSS for clinical-grade fidelity)
* **LLM Backends**: OpenAI API (function calling), Anthropic Claude API (`tool_use`), Ollama (local, JSON mode)
* **Provider Routing**: `Provider` enum + `BaseExtractionPipeline` ABC with one shared `TOOL_SCHEMAS` definition — no third-party orchestration framework
* **PDF / Word Parsing**: PyMuPDF (text + page rendering) + pdfplumber (table extraction) + python-docx (Word ingestion)
* **Document Modeling**: `ParsedDocument` with positional metadata; fuzzy quote resolution (rapidfuzz) for citation bounding boxes
* **Scoring**: Deterministic Python engine — the LLM fills a JSON feature vector, Python calculates the score (the "safety valve" pattern)
* **Reporting**: fpdf2 + kaleido for PDF report export; JSON audit-log export for regulatory submissions
* **Testing**: pytest suite (54 tests) covering scoring, extraction validation, provider routing, and Gradio app smoke tests

---

## About the Project

This project was developed by **Sachin Patel** during the **MS in Applied Data Science program at the University of Chicago**. The inspiration for ProtoScore stems from real-world experience at Tempus AI, where the need to replace "gut-feel" in oncology trial design with data-driven decision-making became apparent.

**Vision**: To make clinical development more efficient and accessible by demystifying the decision-making process through safe, explainable AI.

---

## Local Installation & Usage

### 1. Clone the repository

```bash
git clone https://github.com/sachinpatel9/protoscore-oncology.git
cd protoscore-oncology
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

Python 3.10+ is required.

### 3. Configure environment variables

Copy the example file and fill in keys for whichever providers you intend to use:

```bash
cp .env.example .env
```

You only need a key for the provider(s) you select in the UI:

#### OpenAI (Cloud)
Set `OPENAI_API_KEY` in `.env`. Get a key at <https://platform.openai.com/api-keys>.

#### Claude (Cloud)
Set `ANTHROPIC_API_KEY` in `.env`. Get a key at <https://console.anthropic.com/settings/keys>.

#### Ollama (Local) — no API key needed

```bash
# Install from https://ollama.com, then:
ollama serve
```

Select **"Ollama (Local)"** in the UI dropdown. The recommended model auto-pulls on first run based on your available RAM.

### 4. Launch the app

```bash
python app.py
```

The app starts on <http://localhost:7860>.

### 5. Run the test suite (optional)

```bash
pytest tests/ -v
```

The suite mocks all external SDKs by default; one optional test (`tests/test_openai_pipeline.py`) hits a live OpenAI endpoint when `OPENAI_API_KEY` is set, and skips otherwise.

---

## Usage Modes

* **Demo Protocols** — three pre-loaded protocols with varied complexity (LOW / MED / HIGH) for fast exploration without uploading anything.
* **Upload Protocol** — drop in a real PDF or Word protocol; the 3-agent extraction pipeline (Logic / Table / Temporal) populates the JSON feature vector and scores it deterministically.

The **Optimization Simulator** tab supports what-if analysis on visits, invasive procedures, site count, and target N — useful for sponsor negotiations and feasibility committee reviews.

---

## Project Structure

```
app.py                  # Gradio application entry point
requirements.txt        # Python dependencies
.env.example            # Template for provider API keys
tests/                  # pytest suite + test fixtures

logic/
  ai_extractor.py       # Provider enum + 3 BaseExtractionPipeline subclasses
  ollama_utils.py       # Ollama connectivity, model tiers, status pills
  pdf_parser.py         # PDF/Word ingestion with positional metadata
  pii_scrubber.py       # Regex PII detection before LLM calls
  prompts.py            # System + agent-specific prompts
  provenance.py         # Citation models + fuzzy quote resolution
  scoring.py            # PCS calculation + formula display
  enrollment_projector.py  # Pillar E rate projection
  audit_log.py          # HITL verification state + audit log export
  data_manager.py       # Demo protocol data

ui/
  layout.py             # Brand colors, CSS, header HTML
  scorecard.py          # Score display, metric cards, radar chart
  pdf_viewer.py         # PDF page rendering + citation highlights
  verification.py       # Batch HITL verification panel
  progress.py           # Extraction progress stepper
  export.py             # PDF report generation
```

---

## License

MIT
