"""
OpenAI extraction pipeline.

Uses OpenAI's function-calling API for structured output. The Anthropic-style
tool defs in `base.py::_TOOL_BY_NAME` are wrapped into OpenAI's
`{"type": "function", "function": {...}}` shape inline.

### Default model

Defaults to ``gpt-5.4-mini`` — same generation as the current frontier
``gpt-5.4`` (so reasoning quality is comparable for constrained
JSON-extraction workloads) but mini-tier RPM (~hundreds/min vs. 3/min for the
flagship), so the 5 sequential agent calls in a single extraction run do not
trip rate limits.

### Override

Set ``OPENAI_MODEL`` in the environment to use a different chat-completions
model. Examples: ``gpt-5.5`` (flagship, slower), ``gpt-4.1-mini`` (cheaper),
``gpt-5.4`` (highest reasoning, but 3 RPM on most accounts).

### Rate-limit handling

``_call_llm`` wraps the SDK call in :py:meth:`_retry_on_rate_limit`, which
retries up to 3 times on ``openai.RateLimitError`` with exponential backoff
(2 s, 4 s, 8 s). Defense-in-depth: even with a high-RPM default, a burst
across multiple users on the same account can still hit the per-minute cap.

### gpt-5.x token kwarg

Use ``max_completion_tokens=`` not ``max_tokens=`` — the latter is rejected
with HTTP 400 on gpt-5.x.
"""

import json
import logging
import os
import time

from logic.pdf_parser import ParsedDocument
from logic.pii_scrubber import scrub_pii
from logic.prompts import SYSTEM_PROMPT
from logic.providers.base import (
    BaseExtractionPipeline,
    TOOL_SCHEMAS,
    _TOOL_BY_NAME,
)

logger = logging.getLogger(__name__)


# Default chosen for high RPM + strong reasoning on structured extraction.
# The user can override at runtime with the OPENAI_MODEL env var.
DEFAULT_MODEL = "gpt-5.4-mini"


class OpenAIExtractionPipeline(BaseExtractionPipeline):
    """OpenAI extraction using function calling for structured output."""

    def __init__(self, api_key: str, parsed_doc: ParsedDocument):
        super().__init__(parsed_doc)
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self._model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def MODEL(self) -> str:  # noqa: N802 — kept as instance property for backward compat
        """Backward-compat alias used by older callers and tests."""
        return self._model

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

        def _do_call():
            return self.client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": scrubbed_prompt},
                ],
                tools=[function_def],
                tool_choice={"type": "function", "function": {"name": tool_name}},
                max_completion_tokens=8192,
            )

        response = self._retry_on_rate_limit(_do_call)

        msg = response.choices[0].message
        if not msg.tool_calls:
            return {}
        return json.loads(msg.tool_calls[0].function.arguments)

    @staticmethod
    def _retry_on_rate_limit(fn, max_retries: int = 3, base_delay: float = 2.0):
        """
        Retry `fn()` on openai.RateLimitError with exponential backoff.

        Backoff schedule: 2s, 4s, 8s. Re-raises on the final attempt so the
        caller (`run_extraction` in app.py) can surface a tailored
        user-facing error.
        """
        import openai
        last_err = None
        for attempt in range(max_retries):
            try:
                return fn()
            except openai.RateLimitError as e:
                last_err = e
                if attempt == max_retries - 1:
                    break
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "OpenAI rate limit hit (attempt %d/%d), retrying in %.0fs",
                    attempt + 1, max_retries, delay,
                )
                time.sleep(delay)
        # Exhausted retries — re-raise the last RateLimitError.
        raise last_err
