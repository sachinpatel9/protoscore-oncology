"""
Unit tests for LLM provider routing.

All real API calls are mocked. The same dropdown label must always route
to the matching pipeline class, and missing API keys must produce a
clear, descriptive error rather than a cryptic SDK exception.
"""

import json
from unittest.mock import patch, MagicMock

import pytest

import app
from logic.ai_extractor import (
    ExtractionPipeline,
    OllamaExtractionPipeline,
    OpenAIExtractionPipeline,
    Provider,
)


# ---------------------------------------------------------------------------
# Provider enum + label mapping
# ---------------------------------------------------------------------------

def test_provider_enum_has_all_three_members():
    assert {p.name for p in Provider} == {"ANTHROPIC", "OPENAI", "OLLAMA"}


def test_provider_by_label_mapping():
    assert app.PROVIDER_BY_LABEL["OpenAI (Cloud)"] is Provider.OPENAI
    assert app.PROVIDER_BY_LABEL["Claude (Cloud)"] is Provider.ANTHROPIC
    assert app.PROVIDER_BY_LABEL["Ollama (Local)"] is Provider.OLLAMA


# ---------------------------------------------------------------------------
# Each pipeline calls only its own SDK
# ---------------------------------------------------------------------------

def test_openai_pipeline_calls_openai_sdk(
    minimal_parsed_doc, mock_openai_client, mock_endpoints_payload,
):
    with patch("openai.OpenAI", return_value=mock_openai_client) as openai_ctor:
        pipeline = OpenAIExtractionPipeline("fake-key", minimal_parsed_doc)
        result = pipeline._call_llm("extract endpoints", "extract_endpoints")

    openai_ctor.assert_called_once_with(api_key="fake-key")
    mock_openai_client.chat.completions.create.assert_called_once()

    call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
    # Function-calling shape, not Anthropic tool_use
    assert call_kwargs["tools"][0]["type"] == "function"
    assert call_kwargs["tools"][0]["function"]["name"] == "extract_endpoints"
    assert call_kwargs["tool_choice"] == {"type": "function", "function": {"name": "extract_endpoints"}}
    assert result == mock_endpoints_payload


def test_anthropic_pipeline_calls_anthropic_sdk(
    minimal_parsed_doc, mock_anthropic_client, mock_endpoints_payload,
):
    with patch("logic.ai_extractor.anthropic.Anthropic", return_value=mock_anthropic_client) as anth_ctor:
        pipeline = ExtractionPipeline("fake-key", minimal_parsed_doc)
        result = pipeline._call_llm("extract endpoints", "extract_endpoints")

    anth_ctor.assert_called_once_with(api_key="fake-key")
    mock_anthropic_client.messages.create.assert_called_once()

    call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
    # Anthropic tool_use shape
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "extract_endpoints"}
    assert call_kwargs["tools"][0]["name"] == "extract_endpoints"
    assert "input_schema" in call_kwargs["tools"][0]
    assert result == mock_endpoints_payload


def test_ollama_pipeline_calls_ollama_chat(minimal_parsed_doc, mock_endpoints_payload):
    with patch("logic.ollama_utils.call_ollama_chat", return_value=mock_endpoints_payload) as oll_call:
        pipeline = OllamaExtractionPipeline("llama3.1:8b", minimal_parsed_doc)
        result = pipeline._call_llm("extract endpoints", "extract_endpoints")

    oll_call.assert_called()
    kwargs = oll_call.call_args.kwargs
    assert kwargs["model"] == "llama3.1:8b"
    assert kwargs["json_mode"] is True
    assert result == mock_endpoints_payload


def test_no_real_sdk_constructors_called_when_other_provider_selected(minimal_parsed_doc):
    """Sentinel: instantiating one provider must not touch the others' SDK constructors."""
    with patch("openai.OpenAI") as openai_ctor, \
         patch("logic.ai_extractor.anthropic.Anthropic") as anth_ctor, \
         patch("logic.ollama_utils.call_ollama_chat") as oll_call:
        OllamaExtractionPipeline("llama3.1:8b", minimal_parsed_doc)
        openai_ctor.assert_not_called()
        anth_ctor.assert_not_called()
        oll_call.assert_not_called()


# ---------------------------------------------------------------------------
# Missing API keys yield descriptive errors via run_extraction
# ---------------------------------------------------------------------------

def _drain_first_yield(generator):
    """Pull the first yield from the generator and return it."""
    return next(generator)


def test_missing_openai_key_yields_descriptive_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    gen = app.run_extraction(file_path="/nonexistent.pdf", llm_provider="OpenAI (Cloud)")
    yielded = _drain_first_yield(gen)
    error_msg = yielded[6]  # error_display slot
    assert "OPENAI_API_KEY not found" in error_msg
    assert ".env" in error_msg
    # Generator must terminate after the early-return
    with pytest.raises(StopIteration):
        next(gen)


def test_missing_anthropic_key_yields_descriptive_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    gen = app.run_extraction(file_path="/nonexistent.pdf", llm_provider="Claude (Cloud)")
    yielded = _drain_first_yield(gen)
    error_msg = yielded[6]
    assert "ANTHROPIC_API_KEY not found" in error_msg
    assert ".env" in error_msg
    with pytest.raises(StopIteration):
        next(gen)


def test_missing_keys_do_not_invoke_sdk_constructors(monkeypatch):
    """Sentinel: when API key is missing, no SDK constructor is touched."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with patch("openai.OpenAI") as openai_ctor, \
         patch("logic.ai_extractor.anthropic.Anthropic") as anth_ctor:

        # OpenAI path with missing key
        gen = app.run_extraction("/x.pdf", "OpenAI (Cloud)")
        next(gen)
        openai_ctor.assert_not_called()

        # Anthropic path with missing key
        gen = app.run_extraction("/x.pdf", "Claude (Cloud)")
        next(gen)
        anth_ctor.assert_not_called()
