"""
Provider registry for ProtoScore V2.

Centralizes:
- The `Provider` enum (single source of truth for which backends exist).
- `PROVIDER_BY_LABEL`: dropdown label → enum mapping consumed by `app.py`.
- `get_pipeline_class(provider)`: factory that returns the concrete pipeline
  class for a given enum member, used to dispatch a single `run_extraction`
  call without scattering `if provider is Provider.X` branches.

To add a new provider:
1. Create `logic/providers/<name>.py` with a `BaseExtractionPipeline` subclass.
2. Add the enum member here.
3. Add the dropdown label → enum entry in `PROVIDER_BY_LABEL`.
4. Wire the class into `_PIPELINE_CLASSES`.
5. Re-export the new class from `logic/providers/__init__.py`.
"""

from enum import Enum


class Provider(Enum):
    """Supported LLM providers for the extraction pipeline."""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OLLAMA = "ollama"


PROVIDER_BY_LABEL: dict[str, Provider] = {
    "OpenAI (Cloud)": Provider.OPENAI,
    "Claude (Cloud)": Provider.ANTHROPIC,
    "Ollama (Local)": Provider.OLLAMA,
}


def get_pipeline_class(provider: Provider):
    """
    Return the concrete `BaseExtractionPipeline` subclass for a provider.

    Imports are local so the registry has no module-level dependency on the
    SDK-bearing provider files (avoids importing `openai` at module load
    when the user has only Anthropic configured, etc.).
    """
    if provider is Provider.ANTHROPIC:
        from logic.providers.anthropic import ExtractionPipeline
        return ExtractionPipeline
    if provider is Provider.OPENAI:
        from logic.providers.openai import OpenAIExtractionPipeline
        return OpenAIExtractionPipeline
    if provider is Provider.OLLAMA:
        from logic.providers.ollama import OllamaExtractionPipeline
        return OllamaExtractionPipeline
    raise ValueError(f"Unknown provider: {provider!r}")
