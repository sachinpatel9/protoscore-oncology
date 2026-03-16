"""
Extraction pipeline progress display for ProtoScore V2.
Design: Clinical Design System
"""


PIPELINE_STEPS = [
    ("Parsing document...", 0.10),
    ("PII safety check...", 0.15),
    ("Analyzing document structure...", 0.20),
    ("Logic Agent: Extracting I/E criteria...", 0.35),
    ("Table Agent: Extracting visit schedule...", 0.55),
    ("Temporal Agent: Mapping procedures...", 0.70),
    ("Extracting study endpoints...", 0.85),
    ("Assembling results...", 0.95),
    ("Extraction complete.", 1.00),
]


def build_progress_html(step: str, fraction: float) -> str:
    """Build HTML progress bar with step description."""
    pct = int(fraction * 100)
    bar_color = "#0E7C86"  # Teal throughout

    return f"""
    <div style="background:#FFFFFF; padding:16px; border-radius:12px;
                border:1px solid #E2E8F0; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <div style="font-size:13px; color:#64748B; margin-bottom:8px;
                    font-family:'Nunito Sans', sans-serif;">
            {step}
        </div>
        <div style="background:#E2E8F0; border-radius:6px; height:8px; overflow:hidden;">
            <div style="background:{bar_color}; height:100%; width:{pct}%;
                        border-radius:6px; transition:width 0.3s ease;"></div>
        </div>
        <div style="font-size:11px; color:#94A3B8; margin-top:4px; text-align:right;">
            {pct}%
        </div>
    </div>
    """
