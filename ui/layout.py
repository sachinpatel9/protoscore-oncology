"""
Gradio theme and layout constants for ProtoScore V2.
Warm Clinical / Organic Modern design system.
"""

import gradio as gr


# -- Warm Clinical / Organic Modern palette --
SAGE = "#5B7B6F"
TERRACOTTA = "#C0755B"
BRONZE = "#8B6F4E"
GOLD = "#D4A04A"
WARM_BG = "#FAF7F2"
CARD_BG = "#FFFFFF"
PANEL_BG = "#F5F1EA"
CODE_BG = "#F0EDE6"
TEXT_PRIMARY = "#2C2C2C"
TEXT_SECONDARY = "#6B7280"
TEXT_TERTIARY = "#9CA3AF"
BORDER = "#E5E0D8"
STATUS_GOOD = "#5B7B6F"
STATUS_OK = "#7A9E8E"
STATUS_WARN = "#D4A04A"
STATUS_BAD = "#C0755B"

# Backward-compatible aliases
TEAL = SAGE
DARK_BG = WARM_BG

# Custom CSS for the Gradio app
CUSTOM_CSS = """
    /* --- Google Fonts --- */
    @import url('https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,600;0,700;1,400&family=Nunito+Sans:wght@300;400;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

    /* --- CSS Custom Properties (Design Tokens) --- */
    :root {
        --ps-bg: #FAF7F2;
        --ps-panel: #F5F1EA;
        --ps-card: #FFFFFF;
        --ps-code: #F0EDE6;
        --ps-text: #2C2C2C;
        --ps-text-secondary: #6B7280;
        --ps-text-tertiary: #9CA3AF;
        --ps-sage: #5B7B6F;
        --ps-terracotta: #C0755B;
        --ps-bronze: #8B6F4E;
        --ps-gold: #D4A04A;
        --ps-border: #E5E0D8;
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
        --color-accent-soft: rgba(91, 123, 111, 0.1) !important;
        --body-text-color: var(--ps-text) !important;
        --block-label-text-color: var(--ps-text-secondary) !important;
        --input-background-fill: var(--ps-card) !important;
        --border-color-primary: var(--ps-border) !important;
        --block-border-color: var(--ps-border) !important;
        --panel-background-fill: var(--ps-panel) !important;
        --button-primary-background-fill: var(--ps-sage) !important;
        --button-primary-background-fill-hover: #4A6A5E !important;
        --button-primary-text-color: white !important;
        --button-secondary-background-fill: var(--ps-panel) !important;
        --button-secondary-text-color: var(--ps-text) !important;
        --button-secondary-border-color: var(--ps-border) !important;
    }

    /* --- Paper texture background --- */
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
    .tab-nav button {
        font-family: var(--ps-font-body) !important;
        font-weight: 600 !important;
        color: var(--ps-text-secondary) !important;
    }
    .tab-nav button.selected {
        color: var(--ps-sage) !important;
        border-color: var(--ps-sage) !important;
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
"""


HEADER_HTML = """
<div style="display:flex; align-items:center; gap:12px; padding:10px 0;
            border-bottom: 1px solid #E5E0D8; margin-bottom: 8px;">
    <div style="font-family:'Lora', Georgia, serif;
                font-size:1.8em; font-weight:700; color:#5B7B6F;">
        ProtoScore
    </div>
    <div style="font-family:'Lora', Georgia, serif;
                font-size:1.4em; font-weight:600; border-left:2px solid #E5E0D8;
                padding-left:12px; color:#C0755B;">
        Oncology
    </div>
    <div style="margin-left:auto; font-size:0.75em; color:#9CA3AF;
                font-family:'Nunito Sans', sans-serif;">
        V2.0
    </div>
</div>
"""
