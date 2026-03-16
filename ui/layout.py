"""
Gradio theme and layout constants for ProtoScore V2.
Clinical design system — cool clinical palette with strict typography hierarchy.
"""

import gradio as gr


# -- Clinical Design System palette --
TEAL = "#0E7C86"       # Primary accent (active states, buttons, highlights)
NAVY = "#0D1B2A"       # Headings and score numbers
RED = "#C0392B"         # High risk indicators only
AMBER = "#E68A00"       # Moderate risk indicators only
GREEN = "#1A7A45"       # Low risk indicators only
BG = "#F8FAFB"          # App background (cool off-white)
CARD_BG = "#FFFFFF"     # Card backgrounds
PANEL_BG = "#F0F4F8"    # Panel/formula backgrounds
CODE_BG = "#EDF2F7"     # Code block backgrounds
TEXT_PRIMARY = "#0D1B2A" # Primary text (navy)
TEXT_SECONDARY = "#64748B" # Labels, metadata
TEXT_TERTIARY = "#94A3B8"  # Hints, disabled
BORDER = "#E2E8F0"      # Borders and rules
FORMULA_TEXT = "#334155" # Formula/code body text

# Backward-compatible aliases
SAGE = TEAL
TERRACOTTA = RED
BRONZE = TEXT_SECONDARY
GOLD = AMBER
WARM_BG = BG
DARK_BG = BG
STATUS_GOOD = GREEN
STATUS_OK = "#3A9CA5"   # Lighter teal for Grade B
STATUS_WARN = AMBER
STATUS_BAD = RED

# Custom CSS for the Gradio app
CUSTOM_CSS = """
    /* --- Google Fonts --- */
    @import url('https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,600;0,700;1,400&family=Nunito+Sans:wght@300;400;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

    /* --- CSS Custom Properties (Design Tokens) --- */
    :root {
        --ps-bg: #F8FAFB;
        --ps-panel: #F0F4F8;
        --ps-card: #FFFFFF;
        --ps-code: #EDF2F7;
        --ps-text: #0D1B2A;
        --ps-text-secondary: #64748B;
        --ps-text-tertiary: #94A3B8;
        --ps-teal: #0E7C86;
        --ps-red: #C0392B;
        --ps-navy: #0D1B2A;
        --ps-amber: #E68A00;
        --ps-green: #1A7A45;
        --ps-border: #E2E8F0;
        --ps-shadow: 0 2px 8px rgba(0,0,0,0.06);
        --ps-shadow-hover: 0 4px 16px rgba(0,0,0,0.10);
        --ps-radius: 12px;
        --ps-radius-sm: 8px;
        --ps-font-display: 'Lora', Georgia, serif;
        --ps-font-body: 'Nunito Sans', 'Segoe UI', sans-serif;
        --ps-font-mono: 'JetBrains Mono', 'Fira Code', monospace;
    }

    /* --- Override Gradio dark theme to light --- */
    .gradio-container {
        background-color: var(--ps-bg) !important;
        font-family: var(--ps-font-body) !important;
        color: var(--ps-text) !important;
    }
    .dark {
        --background-fill-primary: var(--ps-bg) !important;
        --background-fill-secondary: var(--ps-panel) !important;
        --block-background-fill: var(--ps-card) !important;
        --body-background-fill: var(--ps-bg) !important;
        --color-accent-soft: rgba(14, 124, 134, 0.1) !important;
        --body-text-color: var(--ps-text) !important;
        --block-label-text-color: var(--ps-text-secondary) !important;
        --input-background-fill: var(--ps-card) !important;
        --border-color-primary: var(--ps-border) !important;
        --block-border-color: var(--ps-border) !important;
        --panel-background-fill: var(--ps-panel) !important;
        --button-primary-background-fill: var(--ps-teal) !important;
        --button-primary-background-fill-hover: #0A6670 !important;
        --button-primary-text-color: white !important;
        --button-secondary-background-fill: var(--ps-panel) !important;
        --button-secondary-text-color: var(--ps-text) !important;
        --button-secondary-border-color: var(--ps-border) !important;
    }

    /* --- Subtle texture background --- */
    .gradio-container::before {
        content: '';
        position: fixed;
        top: 0; left: 0; width: 100%; height: 100%;
        background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.015'/%3E%3C/svg%3E");
        pointer-events: none;
        z-index: 0;
    }

    /* --- Metric cards grid --- */
    .metric-grid {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 10px;
    }

    /* --- Tabs styling --- */
    .tab-nav {
        border-bottom: 2px solid #E2E8F0 !important;
    }
    .tab-nav button {
        font-family: var(--ps-font-body) !important;
        font-weight: 600 !important;
        color: #64748B !important;
        border-bottom: 2px solid transparent !important;
        margin-bottom: -2px !important;
    }
    .tab-nav button.selected {
        color: #0E7C86 !important;
        border-bottom: 2px solid #0E7C86 !important;
    }

    /* --- Mode selector pill toggle --- */
    .mode-toggle {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
    }
    .mode-toggle .wrap {
        background: #F1F5F9 !important;
        border-radius: 24px !important;
        padding: 4px !important;
        gap: 0 !important;
    }
    .mode-toggle label {
        padding: 6px 20px !important;
        border-radius: 20px !important;
        color: #64748B !important;
        background: transparent !important;
        border: none !important;
        font-size: 13px !important;
        font-family: var(--ps-font-body) !important;
        cursor: pointer !important;
        transition: all 0.2s ease !important;
    }
    .mode-toggle label.selected {
        background: #0E7C86 !important;
        color: #FFFFFF !important;
    }
    .mode-toggle .hide, .mode-toggle > label:first-child {
        display: none !important;
    }

    /* --- LLM Provider selector --- */
    .llm-selector label span {
        font-size: 11px !important;
        text-transform: uppercase !important;
        letter-spacing: 0.06em !important;
        color: #64748B !important;
    }
    .llm-selector select,
    .llm-selector input,
    .llm-selector .wrap-inner {
        border: 1px solid #CBD5E1 !important;
        border-radius: 6px !important;
        background: #FFFFFF !important;
    }

    /* --- PDF viewer panel --- */
    .pdf-panel {
        border: 1px solid var(--ps-border);
        border-radius: var(--ps-radius);
        padding: 10px;
        background: var(--ps-card);
        box-shadow: var(--ps-shadow);
    }

    /* --- Batch verification table (UX-2.1) --- */
    .verification-table table {
        font-size: 0.85em !important;
        font-family: var(--ps-font-body) !important;
    }
    .verification-table td {
        white-space: pre-wrap !important;
        word-break: break-word;
        max-width: 250px;
        color: var(--ps-text) !important;
    }
    .verification-table input {
        background: var(--ps-card) !important;
        color: var(--ps-text) !important;
        border: 1px solid var(--ps-border) !important;
    }

    /* --- Card hover transitions --- */
    .ps-card-hover {
        transition: box-shadow 0.2s ease, transform 0.2s ease;
    }
    .ps-card-hover:hover {
        box-shadow: var(--ps-shadow-hover);
        transform: scale(1.01);
    }

    /* --- PDF navigation bar --- */
    .pdf-nav-bar {
        background: #F1F5F9 !important;
        border-radius: 8px !important;
        padding: 8px 16px !important;
        gap: 8px !important;
    }
    .pdf-nav-bar .gr-button, .pdf-nav-bar button {
        min-width: auto !important;
    }
    .pdf-nav-bar input[type="number"] {
        width: 60px !important;
        text-align: center !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 6px !important;
    }
"""


HEADER_HTML = """
<div style="padding:8px 0; border-bottom:1px solid #E2E8F0; margin-bottom:8px;">
    <div style="display:flex; align-items:center; gap:12px;">
        <div style="font-family:'Lora', Georgia, serif;
                    font-size:24px; font-weight:700; color:#0D1B2A;">
            ProtoScore
        </div>
        <div style="font-family:'Lora', Georgia, serif;
                    font-size:24px; font-weight:400; border-left:2px solid #E2E8F0;
                    padding-left:12px; color:#0E7C86;">
            Oncology
        </div>
        <div style="margin-left:auto; font-size:11px; color:#94A3B8;
                    font-family:'Nunito Sans', sans-serif;">
            V2.0
        </div>
    </div>
    <div style="font-size:12px; font-style:italic; color:#64748B; margin-top:4px;
                font-family:'Nunito Sans', sans-serif;">
        Protocol Complexity Intelligence for Oncology Trials
    </div>
</div>
"""
