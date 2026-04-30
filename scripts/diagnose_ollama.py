"""
One-off diagnostic for Phase 1 of the V2.1 polish plan.

Runs the Ollama extraction pipeline against a real protocol PDF, captures
every Ollama HTTP call (status, latency, body excerpt), every JSON parse /
schema validation outcome, and the final extraction state. Output is dumped
to stdout so it can be pasted into tests/testing_logs.md as evidence.

Usage:
    python scripts/diagnose_ollama.py /path/to/Protocol.pdf
"""

import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Force verbose logging from the pipeline + ollama_utils
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

from logic.pdf_parser import parse_protocol_pdf  # noqa: E402
from logic.ai_extractor import OllamaExtractionPipeline  # noqa: E402
from logic import ollama_utils  # noqa: E402


def main(pdf_path: str):
    print("=" * 78)
    print(f"DIAGNOSTIC: Ollama extraction on {pdf_path}")
    print("=" * 78)

    # 1. Connectivity check
    if not ollama_utils.check_ollama_running():
        print("FAIL: Ollama is not reachable at localhost:11434")
        sys.exit(2)

    installed = ollama_utils.get_installed_models()
    print(f"Installed models: {installed}")

    model, tier, rationale = ollama_utils.recommend_model(installed)
    print(f"Recommended model: {model} (tier={tier})")
    print(f"Rationale: {rationale}")

    # 2. Parse the PDF
    print("\n[step] Parsing PDF...")
    t0 = time.time()
    file_bytes = Path(pdf_path).read_bytes()
    parsed = parse_protocol_pdf(file_bytes)
    print(
        f"Parsed in {time.time() - t0:.1f}s: "
        f"{parsed.total_pages} pages, "
        f"{len(parsed.section_hierarchy)} sections in hierarchy"
    )

    # 3. Wrap call_ollama_chat to capture every HTTP request/response
    original_call = ollama_utils.call_ollama_chat
    call_log: list[dict] = []

    def wrapped(*args, **kwargs):
        call_idx = len(call_log)
        prompt_preview = (kwargs.get("user_prompt") or args[2])[:120].replace("\n", " ")
        entry = {
            "idx": call_idx,
            "model": kwargs.get("model") or args[0],
            "prompt_preview": prompt_preview,
            "json_mode": kwargs.get("json_mode", False),
        }
        t = time.time()
        try:
            result = original_call(*args, **kwargs)
            entry["latency_s"] = round(time.time() - t, 1)
            entry["result_type"] = type(result).__name__
            entry["result_preview"] = (
                json.dumps(result)[:200] if isinstance(result, dict) else str(result)[:200]
            )
            entry["result_keys"] = list(result.keys()) if isinstance(result, dict) else None
            print(
                f"  [call {call_idx}] {entry['model']} "
                f"latency={entry['latency_s']}s "
                f"keys={entry['result_keys']} "
                f"preview={entry['result_preview'][:120]}"
            )
            return result
        except Exception as e:
            entry["latency_s"] = round(time.time() - t, 1)
            entry["error"] = f"{type(e).__name__}: {e}"
            print(f"  [call {call_idx}] FAILED after {entry['latency_s']}s: {entry['error']}")
            raise
        finally:
            call_log.append(entry)

    ollama_utils.call_ollama_chat = wrapped
    # Also patch the lazy-imported reference inside the pipeline
    import logic.ollama_utils as _ou
    _ou.call_ollama_chat = wrapped

    # 4. Run the pipeline
    print("\n[step] Running OllamaExtractionPipeline...")
    pipeline = OllamaExtractionPipeline(model, parsed)

    def progress_cb(step: str, fraction: float):
        print(f"  [progress {fraction * 100:5.1f}%] {step}")

    t0 = time.time()
    try:
        result = pipeline.run(progress_callback=progress_cb)
        elapsed = time.time() - t0
        print(f"\n[done] Pipeline completed in {elapsed:.1f}s ({elapsed/60:.1f}min)")
    except Exception as e:
        print(f"\n[FAIL] Pipeline raised {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(3)

    # 5. Inspect result
    print("\n" + "=" * 78)
    print("RESULT SUMMARY")
    print("=" * 78)
    print(f"Source filename: {result.source_filename}")
    print(f"Model used: {result.model_used}")
    print(f"Total pages: {result.total_pages}")
    print(f"\nProtocol data:")
    cm = result.protocol_data["complexity_metrics"]
    pb = result.protocol_data["patient_burden"]
    print(f"  ie_criteria_count: {cm['ie_criteria_count']}")
    print(f"  endpoints_count:   {cm['endpoints_count']}")
    print(f"  total_visits:      {pb['total_visits']}")
    print(f"  invasive_procs:    {pb['invasive_procedures']}")

    print("\nProvenance records:")
    for name, rec in result.provenance.items():
        print(
            f"  {name:30s} value={rec.value!s:>10s} "
            f"conf={rec.confidence_score:.2f} "
            f"citations={len(rec.citations)}"
        )

    zero_metrics = [
        n for n in ["ie_criteria_count", "endpoints_count"]
        if result.protocol_data["complexity_metrics"].get(n, 0) == 0
    ] + [
        n for n in ["total_visits", "invasive_procedures"]
        if result.protocol_data["patient_burden"].get(n, 0) == 0
    ]
    print(f"\nMetrics that came back zero: {zero_metrics}")

    print("\n" + "=" * 78)
    print("CALL LOG")
    print("=" * 78)
    for entry in call_log:
        print(json.dumps(entry, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/diagnose_ollama.py <pdf_path>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
