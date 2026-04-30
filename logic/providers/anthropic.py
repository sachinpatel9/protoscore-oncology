"""
Anthropic Claude extraction pipeline.

Uses Claude's native `tool_use` calling for structured output. The tool
definitions in `base.py::_TOOL_BY_NAME` are already Anthropic-shaped
(`name`/`description`/`input_schema`), so no shape translation is needed.
"""

import anthropic

from logic.pdf_parser import ParsedDocument
from logic.pii_scrubber import scrub_pii
from logic.prompts import SYSTEM_PROMPT
from logic.providers.base import (
    BaseExtractionPipeline,
    _TOOL_BY_NAME,
)


class ExtractionPipeline(BaseExtractionPipeline):
    """Claude API extraction using tool_use for structured output."""

    MODEL = "claude-sonnet-4-20250514"

    def __init__(self, api_key: str, parsed_doc: ParsedDocument):
        super().__init__(parsed_doc)
        self.client = anthropic.Anthropic(api_key=api_key)

    @property
    def model_name(self) -> str:
        return self.MODEL

    def _call_llm(self, user_prompt: str, tool_name: str) -> dict:
        scrubbed_prompt, _ = scrub_pii(user_prompt)

        tool_def = _TOOL_BY_NAME[tool_name]

        response = self.client.messages.create(
            model=self.MODEL,
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": scrubbed_prompt}],
            tools=[tool_def],
            tool_choice={"type": "tool", "name": tool_name},
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                return block.input

        return {}
