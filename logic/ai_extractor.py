"""
Backward-compatibility shim for the pre-V2.1 single-file provider layout.

The actual provider implementations now live under `logic.providers/` (one
file per provider). This module re-exports the public API so callers and
tests using the legacy `logic.ai_extractor.*` import paths keep working.

New code should import from `logic.providers` directly:

    from logic.providers import (
        Provider, PROVIDER_BY_LABEL, get_pipeline_class,
        ExtractionPipeline, OpenAIExtractionPipeline, OllamaExtractionPipeline,
        BaseExtractionPipeline, TOOL_SCHEMAS,
    )
"""

# Re-export the public surface for legacy imports.
from logic.providers import (  # noqa: F401
    BaseExtractionPipeline,
    TOOL_SCHEMAS,
    Provider,
    PROVIDER_BY_LABEL,
    get_pipeline_class,
    ExtractionPipeline,
    OpenAIExtractionPipeline,
    OllamaExtractionPipeline,
)

# `anthropic` is re-imported here so test patches targeting
# `logic.ai_extractor.anthropic.Anthropic` continue to resolve. Because
# `anthropic` is a singleton module, patching the attribute on either
# `logic.ai_extractor.anthropic` or `logic.providers.anthropic.anthropic`
# affects the same `Anthropic` class — both paths work.
import anthropic  # noqa: F401

__all__ = [
    "BaseExtractionPipeline",
    "TOOL_SCHEMAS",
    "Provider",
    "PROVIDER_BY_LABEL",
    "get_pipeline_class",
    "ExtractionPipeline",
    "OpenAIExtractionPipeline",
    "OllamaExtractionPipeline",
]
