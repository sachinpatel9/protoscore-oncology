"""
Smoke tests for the Gradio app:
- App initializes
- Three remaining tabs exist (after AI Insights removal)
- All three demo protocols load without errors
"""

import plotly.graph_objects as go
import pytest

import app


def _tab_labels(blocks_app):
    return [
        c.label for c in blocks_app.blocks.values() if type(c).__name__ == "Tab"
    ]


# ---------------------------------------------------------------------------
# App initialization
# ---------------------------------------------------------------------------

def test_build_app_does_not_raise():
    blocks = app.build_app()
    assert blocks is not None
    # Sanity: real Blocks instances expose a `.blocks` dict of components
    assert hasattr(blocks, "blocks")


# ---------------------------------------------------------------------------
# Tab structure
# ---------------------------------------------------------------------------

def test_three_tabs_remain_after_ai_insights_removal():
    blocks = app.build_app()
    labels = _tab_labels(blocks)
    assert set(labels) == {
        "Assessment Dashboard",
        "Batch Verification",
        "Optimization Simulator",
    }, f"unexpected tab set: {labels}"


def test_ai_insights_tab_no_longer_exists():
    blocks = app.build_app()
    labels = _tab_labels(blocks)
    assert "AI Insights" not in labels


# ---------------------------------------------------------------------------
# Demo protocols load
# ---------------------------------------------------------------------------

def test_get_demo_options_returns_three_protocols():
    options = app.get_demo_options()
    assert len(options) == 3
    assert set(options) == {
        "ONC-112-PhaseII",
        "ONC-301-PhaseIII",
        "HEM-045-PhaseI/II",
    }


@pytest.mark.parametrize("protocol_id", [
    "ONC-112-PhaseII",
    "ONC-301-PhaseIII",
    "HEM-045-PhaseI/II",
])
def test_demo_protocol_loads_without_error(protocol_id):
    """run_demo_analysis must return a 4-tuple of (str, Figure, str, str)."""
    result = app.run_demo_analysis(protocol_id)

    assert isinstance(result, tuple)
    assert len(result) == 4, f"expected 4-tuple, got len={len(result)}"
    scorecard_html, radar_fig, formula_html, info_html = result

    assert isinstance(scorecard_html, str) and scorecard_html
    assert isinstance(radar_fig, go.Figure)
    assert isinstance(formula_html, str) and formula_html
    assert isinstance(info_html, str) and info_html
