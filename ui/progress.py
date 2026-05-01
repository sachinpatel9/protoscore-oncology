"""
Extraction pipeline progress display for ProtoScore V2.

Renders a single, self-contained HTML progress bar into the scorecard slot.
The default Gradio queue progress overlay is suppressed at the event level
via `show_progress="hidden"` on `analyze_btn.click(...)` in `app.py` — this
file is the only progress UI the user sees during extraction.

Includes a heuristic ETA (linear extrapolation from elapsed × remaining)
and a subtle CSS pulse on the active step so the bar visibly "breathes"
during long Ollama steps that can take 2-3 minutes to complete.
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


def _format_seconds(s: float) -> str:
    """Format seconds as `M:SS` (≥1 min) or `Ns` (<1 min)."""
    total = max(0, int(s))
    mins, secs = divmod(total, 60)
    return f"{mins}:{secs:02d}" if mins > 0 else f"{secs}s"


def build_progress_html(
    step: str,
    fraction: float,
    elapsed_seconds: float = 0,
    show_ollama_hint: bool = False,
) -> str:
    """Build HTML progress bar with agent status, elapsed, and ETA.

    Args:
        step: Current pipeline step (e.g. "Logic Agent: Extracting I/E criteria...").
        fraction: Progress fraction in [0.0, 1.0].
        elapsed_seconds: Seconds since the extraction started.
        show_ollama_hint: When True, render a sub-line warning the user that
            local extraction can take several minutes — used by the Ollama
            path so users don't think the run has hung.
    """
    pct = int(max(0.0, min(1.0, fraction)) * 100)
    elapsed_str = _format_seconds(elapsed_seconds)

    # Heuristic ETA: extrapolate from observed throughput. Suppress until
    # we have enough signal (>5%) so we don't show wildly inaccurate numbers
    # in the first second or two.
    if fraction >= 1.0:
        eta_str = "Done"
    elif fraction > 0.05 and elapsed_seconds > 0:
        eta_seconds = elapsed_seconds * (1 - fraction) / fraction
        eta_str = f"~{_format_seconds(eta_seconds)} remaining"
    else:
        eta_str = "Estimating..."

    ollama_hint_html = ""
    if show_ollama_hint and fraction < 1.0:
        ollama_hint_html = (
            '<div style="font-size:11px; color:#94A3B8; margin-top:4px; '
            'font-family:\'Nunito Sans\', sans-serif;">'
            'Local extraction can take 5–10 min on a 70-page protocol — sit tight.'
            '</div>'
        )

    # Pulse the step text only while the run is in progress; once done,
    # render it static (no animation) so the "Extraction complete." line
    # doesn't keep blinking.
    step_class = "progress-step-active" if fraction < 1.0 else "progress-step-done"

    return f"""
    <div style="padding:12px 0;">
        <div style="display:flex; justify-content:space-between; align-items:center;
                    margin-bottom:6px;">
            <span class="{step_class}" style="font-size:12px; color:#0E7C86;
                         font-family:'JetBrains Mono', 'Fira Code', monospace;">
                {step} {pct}%
            </span>
            <span style="font-size:12px; color:#94A3B8;
                         font-family:'JetBrains Mono', 'Fira Code', monospace;">
                {elapsed_str} &middot; {eta_str}
            </span>
        </div>
        <div style="background:#E2E8F0; border-radius:6px; height:6px; overflow:hidden;">
            <div style="background:#0E7C86; height:100%; width:{pct}%;
                        border-radius:6px; transition:width 0.3s ease;"></div>
        </div>
        {ollama_hint_html}
    </div>
    """
