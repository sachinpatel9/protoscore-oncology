"""
Ollama local-LLM extraction pipeline.

Uses Ollama's `/api/chat` JSON mode (no native tool-use). The expected JSON
schema is appended to the user prompt as an instruction, and the response is
parsed as a top-level JSON object. A strict-prompt retry runs if the first
attempt fails to validate against the schema's required fields.

Mocking note (CLAUDE.md test conventions): patch `logic.ollama_utils.call_ollama_chat`
(the defining module). The function is imported lazily inside `_call_llm`, so
patching it on `logic.providers.ollama` does NOT propagate.
"""

import json
import logging

from logic.pdf_parser import ParsedDocument
from logic.pii_scrubber import scrub_pii
from logic.prompts import SYSTEM_PROMPT
from logic.providers.base import (
    BaseExtractionPipeline,
    TOOL_SCHEMAS,
)

logger = logging.getLogger(__name__)


class OllamaExtractionPipeline(BaseExtractionPipeline):
    """Ollama local LLM extraction using JSON-mode prompts."""

    def __init__(self, model: str, parsed_doc: ParsedDocument):
        super().__init__(parsed_doc)
        self._model = model

    @property
    def model_name(self) -> str:
        return f"ollama/{self._model}"

    def _call_llm(self, user_prompt: str, tool_name: str) -> dict:
        from logic.ollama_utils import call_ollama_chat

        scrubbed_prompt, _ = scrub_pii(user_prompt)

        schema = TOOL_SCHEMAS[tool_name]
        schema_instruction = (
            "\n\n---\n"
            "IMPORTANT: Respond with ONLY a valid JSON object matching this exact schema. "
            "Do not include any text before or after the JSON.\n\n"
            f"Required JSON schema:\n```json\n{json.dumps(schema, indent=2)}\n```"
        )

        full_prompt = scrubbed_prompt + schema_instruction

        try:
            result = call_ollama_chat(
                model=self._model,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=full_prompt,
                json_mode=True,
            )
            if self._validate_result(result, tool_name):
                return result
        except Exception as e:
            logger.warning(f"Ollama first attempt failed for {tool_name}: {e}")

        logger.info(f"Retrying {tool_name} with stricter prompt")
        strict_prompt = (
            f"You MUST respond with valid JSON only. No explanations.\n\n"
            f"{scrubbed_prompt}\n\n"
            f"Output ONLY this JSON structure:\n{json.dumps(schema, indent=2)}"
        )

        try:
            result = call_ollama_chat(
                model=self._model,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=strict_prompt,
                json_mode=True,
            )
            if result:
                return result
        except Exception as e:
            logger.error(f"Ollama retry failed for {tool_name}: {e}")

        return self._empty_result(tool_name)

    def _validate_result(self, result: dict, tool_name: str) -> bool:
        schema = TOOL_SCHEMAS.get(tool_name, {})
        required = schema.get("required", [])
        return all(key in result for key in required)

    def _empty_result(self, tool_name: str) -> dict:
        defaults = {
            "classify_sections": {
                "ie_criteria": {"section_titles": [], "page_numbers": []},
                "endpoints": {"section_titles": [], "page_numbers": []},
                "schedule": {"section_titles": [], "page_numbers": []},
                "procedures": {"section_titles": [], "page_numbers": []},
            },
            "extract_ie_criteria": {
                "total_ie_count": 0,
                "confidence_score": 0.0,
                "inclusion_criteria": [],
                "exclusion_criteria": [],
                "reasoning": "Extraction failed — local model could not parse this section.",
            },
            "extract_visit_schedule": {
                "total_visits": 0,
                "confidence_score": 0.0,
                "reasoning": "Extraction failed — local model could not parse this section.",
            },
            "extract_procedures": {
                "total_invasive_count": 0,
                "confidence_score": 0.0,
                "invasive_procedures": [],
                "burden_spikes": [],
                "reasoning": "Extraction failed — local model could not parse this section.",
            },
            "extract_endpoints": {
                "total_endpoints_count": 0,
                "confidence_score": 0.0,
                "primary_endpoints": [],
                "secondary_endpoints": [],
                "exploratory_endpoints": [],
                "reasoning": "Extraction failed — local model could not parse this section.",
            },
        }
        return defaults.get(tool_name, {})
