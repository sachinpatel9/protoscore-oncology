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


def build_progress_html(step: str, fraction: float, elapsed_seconds: float = 0) -> str:
    """Build HTML progress bar with agent status and elapsed time.

    Args:
        step: Current pipeline step description (e.g. "Logic Agent: Extracting I/E criteria...")
        fraction: Progress fraction 0.0–1.0
        elapsed_seconds: Seconds elapsed since extraction started
    """
    pct = int(fraction * 100)

    # Format elapsed time
    mins = int(elapsed_seconds) // 60
    secs = int(elapsed_seconds) % 60
    elapsed_str = f"{mins}:{secs:02d}" if mins > 0 else f"{secs}s"

    return f"""
    <div style="padding:12px 0;">
        <div style="display:flex; justify-content:space-between; align-items:center;
                    margin-bottom:6px;">
            <span style="font-size:12px; color:#0E7C86;
                         font-family:'JetBrains Mono', 'Fira Code', monospace;">
                {step} {pct}%
            </span>
            <span style="font-size:12px; color:#94A3B8;
                         font-family:'JetBrains Mono', 'Fira Code', monospace;">
                {elapsed_str}
            </span>
        </div>
        <div style="background:#E2E8F0; border-radius:6px; height:6px; overflow:hidden;">
            <div style="background:#0E7C86; height:100%; width:{pct}%;
                        border-radius:6px; transition:width 0.3s ease;"></div>
        </div>
    </div>
    """
