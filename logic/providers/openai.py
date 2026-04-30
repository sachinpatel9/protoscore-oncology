"""
OpenAI extraction pipeline.

Uses OpenAI's function-calling API for structured output. The Anthropic-style
tool defs in `base.py::_TOOL_BY_NAME` are wrapped into OpenAI's
`{"type": "function", "function": {...}}` shape inline.

Note (gpt-5.x): the token-limit kwarg is `max_completion_tokens=`, not
`max_tokens=` (the latter is rejected with HTTP 400 on gpt-5.x).
"""

import json

from logic.pdf_parser import ParsedDocument
from logic.pii_scrubber import scrub_pii
from logic.prompts import SYSTEM_PROMPT
from logic.providers.base import (
    BaseExtractionPipeline,
    TOOL_SCHEMAS,
    _TOOL_BY_NAME,
)


class OpenAIExtractionPipeline(BaseExtractionPipeline):
    """OpenAI extraction using function calling for structured output."""

    MODEL = "gpt-5.4"

    def __init__(self, api_key: str, parsed_doc: ParsedDocument):
        super().__init__(parsed_doc)
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)

    @property
    def model_name(self) -> str:
        return self.MODEL

    def _call_llm(self, user_prompt: str, tool_name: str) -> dict:
        scrubbed_prompt, _ = scrub_pii(user_prompt)

        function_def = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": _TOOL_BY_NAME[tool_name]["description"],
                "parameters": TOOL_SCHEMAS[tool_name],
            },
        }

        response = self.client.chat.completions.create(
            model=self.MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": scrubbed_prompt},
            ],
            tools=[function_def],
            tool_choice={"type": "function", "function": {"name": tool_name}},
            max_completion_tokens=8192,
        )

        msg = response.choices[0].message
        if not msg.tool_calls:
            return {}
        return json.loads(msg.tool_calls[0].function.arguments)
