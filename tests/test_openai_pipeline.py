"""
Live integration test for the OpenAI extraction pipeline.

Requires OPENAI_API_KEY in .env and the account must have access to gpt-5.4.

Run:
    python tests/test_openai_pipeline.py
"""

import os
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from logic.ai_extractor import (
    OpenAIExtractionPipeline,
    Provider,
    TOOL_SCHEMAS,
)
from logic.pdf_parser import ParsedDocument, ParsedPage, TextBlock


load_dotenv()


def _build_minimal_doc() -> ParsedDocument:
    """Construct a one-page synthetic ParsedDocument for the test."""
    snippet = (
        "STUDY ENDPOINTS\n\n"
        "Primary endpoint: Overall response rate (ORR) at 24 weeks.\n"
        "Secondary endpoints: Progression-free survival, duration of response.\n"
        "Exploratory endpoints: Patient-reported quality-of-life scores.\n"
    )
    block = TextBlock(
        text=snippet,
        page_number=1,
        bbox=(0.0, 0.0, 100.0, 100.0),
        section_path=["Endpoints"],
    )
    page = ParsedPage(
        page_number=1,
        raw_text=snippet,
        text_blocks=[block],
        tables=[],
    )
    return ParsedDocument(
        pages=[page],
        section_hierarchy=[{"title": "Endpoints", "page_number": 1}],
        total_pages=1,
    )


def test_provider_enum():
    """Provider enum exposes all three members."""
    members = {p.name for p in Provider}
    assert members == {"ANTHROPIC", "OPENAI", "OLLAMA"}, (
        f"unexpected enum members: {members}"
    )
    print("PASS  Provider enum has ANTHROPIC, OPENAI, OLLAMA")


def test_model_name():
    """Pipeline reports its model identifier."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        print("SKIP  test_model_name (OPENAI_API_KEY not set)")
        return
    doc = _build_minimal_doc()
    pipeline = OpenAIExtractionPipeline(api_key, doc)
    assert pipeline.model_name == "gpt-5.4", (
        f"expected model_name=gpt-5.4, got {pipeline.model_name}"
    )
    print(f"PASS  model_name == {pipeline.model_name}")


def test_live_extract_endpoints():
    """Live API call to gpt-5.4 returns a dict matching the endpoints schema."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        print("SKIP  test_live_extract_endpoints (OPENAI_API_KEY not set)")
        return

    doc = _build_minimal_doc()
    pipeline = OpenAIExtractionPipeline(api_key, doc)

    user_prompt = (
        "Extract the study endpoints from this section.\n\n"
        f"{doc.pages[0].raw_text}"
    )

    result = pipeline._call_llm(user_prompt, "extract_endpoints")

    assert isinstance(result, dict), f"expected dict, got {type(result)}"
    required = TOOL_SCHEMAS["extract_endpoints"].get("required", [])
    missing = [k for k in required if k not in result]
    assert not missing, f"missing required keys: {missing}; got keys: {list(result)}"

    primary = result.get("primary_endpoints", [])
    assert isinstance(primary, list), f"primary_endpoints is not a list: {primary!r}"
    assert len(primary) >= 1, "expected at least one primary endpoint"

    confidence = result.get("confidence_score", -1)
    assert 0.0 <= confidence <= 1.0, f"confidence out of range: {confidence}"

    total = result.get("total_endpoints_count", 0)
    assert total > 0, f"expected total_endpoints_count > 0, got {total}"

    print(f"PASS  live API returned {total} endpoint(s) with confidence {confidence}")
    print(f"      primary[0]: {primary[0].get('name', '<no name>')}")


def main() -> int:
    failures = 0
    for fn in (test_provider_enum, test_model_name, test_live_extract_endpoints):
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
            failures += 1
        except Exception as e:
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failures += 1

    if failures:
        print(f"\n{failures} test(s) failed")
        return 1
    print("\nAll tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
