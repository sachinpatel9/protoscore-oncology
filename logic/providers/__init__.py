"""
Public API for the LLM provider layer.

Re-exports the base class, the registry (Provider enum + label map + factory),
and the three concrete pipeline classes. New code should import from
`logic.providers` directly; `logic.ai_extractor` is a thin backward-compat
shim around this package.
"""

from logic.providers.base import BaseExtractionPipeline, TOOL_SCHEMAS
from logic.providers.registry import (
    Provider,
    PROVIDER_BY_LABEL,
    get_pipeline_class,
)
from logic.providers.anthropic import ExtractionPipeline
from logic.providers.openai import OpenAIExtractionPipeline
from logic.providers.ollama import OllamaExtractionPipeline

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
