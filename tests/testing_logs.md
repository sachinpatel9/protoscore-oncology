# Testing Logs — ProtoScore V2

Structured record of test failures: what was run, the output, suspected cause, the proposed fix, and the resolution applied (if any). Resolved entries are kept as a permanent record of the fix; unresolved entries are raised to the maintainer for a decision before any commit lands.

---

## 2026-04-30 · Initial run of pytest test suite

**Status**: ✅ **RESOLVED** — all 4 failures fixed in the same commit as the suite landed.

| Field | Value |
|---|---|
| Date discovered | 2026-04-30 |
| Date resolved | 2026-04-30 |
| Resolved in commit | `f6db4db` (`test: add pytest suite for scoring, extraction, provider routing, and smoke tests`) |
| Approval | User answered `Execute now` to the proposed fix on 2026-04-30 |
| Initial result | 4 failed, 50 passed |
| Post-fix result | **54 passed, 0 failed** (`pytest tests/ -v` → `54 passed, 8 warnings in 5.54s`) |
| Verification command | `python -m pytest tests/ -v` |

### Common root cause

All four failures shared a single root cause. Tests patched `logic.ai_extractor.call_ollama_chat`, but that name is **not** a module-level attribute of `logic.ai_extractor`. It's imported lazily inside `OllamaExtractionPipeline._call_llm`:

```python
# logic/ai_extractor.py, inside OllamaExtractionPipeline._call_llm
def _call_llm(self, user_prompt: str, tool_name: str) -> dict:
    from logic.ollama_utils import call_ollama_chat
    ...
```

`unittest.mock.patch` only succeeds against attributes that exist on the target module at patch-creation time. Since the import only happens *during* method execution, the attribute isn't present at patch time — and even after, it's a function-local binding, not a module attribute.

### Fix applied

Patch the function at its **defining module** (`logic.ollama_utils.call_ollama_chat`) instead of at the consuming module. Python rebinds the name on use, so any caller (including the lazy import inside the pipeline) picks up the patched version.

Pure test-bug fix — no source-code change. One-line edit at four sites across two test files.

---

### Failure 1 — `tests/test_extraction.py::test_schema_consistency_ollama`

**Output**:

```
AttributeError: <module 'logic.ai_extractor' from '...'> does not have the attribute 'call_ollama_chat'
  File "tests/test_extraction.py:171",
    with patch("logic.ai_extractor.call_ollama_chat", return_value=mock_endpoints_payload):
```

**Proposed fix**: change patch target to `logic.ollama_utils.call_ollama_chat`.

**Recommendation**: `Execute now` (test bug, trivial, no behavior change).

**Resolution applied** — 2026-04-30, commit `f6db4db`:

```diff
- with patch("logic.ai_extractor.call_ollama_chat", return_value=mock_endpoints_payload):
+ with patch("logic.ollama_utils.call_ollama_chat", return_value=mock_endpoints_payload):
```

Test now passes.

---

### Failure 2 — `tests/test_extraction.py::test_schema_parity_across_all_three_providers`

**Output**:

```
AttributeError: <module 'logic.ai_extractor' ...> does not have the attribute 'call_ollama_chat'
  File "tests/test_extraction.py:196",
    with patch("logic.ai_extractor.call_ollama_chat", return_value=mock_endpoints_payload):
```

**Proposed fix**: change patch target to `logic.ollama_utils.call_ollama_chat`.

**Recommendation**: `Execute now`.

**Resolution applied** — 2026-04-30, commit `f6db4db`:

```diff
- with patch("logic.ai_extractor.call_ollama_chat", return_value=mock_endpoints_payload):
+ with patch("logic.ollama_utils.call_ollama_chat", return_value=mock_endpoints_payload):
```

Test now passes.

---

### Failure 3 — `tests/test_providers.py::test_ollama_pipeline_calls_ollama_chat`

**Output**:

```
AttributeError: <module 'logic.ai_extractor' ...> does not have the attribute 'call_ollama_chat'
  File "tests/test_providers.py:78",
    with patch("logic.ai_extractor.call_ollama_chat", return_value=mock_endpoints_payload) as oll_call:
```

**Proposed fix**: change patch target to `logic.ollama_utils.call_ollama_chat`.

**Recommendation**: `Execute now`.

**Resolution applied** — 2026-04-30, commit `f6db4db`:

```diff
- with patch("logic.ai_extractor.call_ollama_chat", return_value=mock_endpoints_payload) as oll_call:
+ with patch("logic.ollama_utils.call_ollama_chat", return_value=mock_endpoints_payload) as oll_call:
```

Test now passes.

---

### Failure 4 — `tests/test_providers.py::test_no_real_sdk_constructors_called_when_other_provider_selected`

**Output**:

```
AttributeError: <module 'logic.ai_extractor' ...> does not have the attribute 'call_ollama_chat'
  File "tests/test_providers.py:93",
    patch("logic.ai_extractor.call_ollama_chat") as oll_call:
```

**Proposed fix**: change patch target to `logic.ollama_utils.call_ollama_chat`.

**Recommendation**: `Execute now`.

**Resolution applied** — 2026-04-30, commit `f6db4db`:

```diff
-      patch("logic.ai_extractor.call_ollama_chat") as oll_call:
+      patch("logic.ollama_utils.call_ollama_chat") as oll_call:
```

Test now passes.

---

## 2026-04-30 · Live diagnostic: "Ollama execution was not successful" report

**Status**: ✅ **NO BUG** — Ollama path runs end-to-end and produces correct results. Reported failure was a UX issue, not a logic issue. Remediation lives in Phase 4 of the V2.1 polish plan (progress bar consolidation + ETA).

| Field | Value |
|---|---|
| Date diagnosed | 2026-04-30 |
| Symptom reported | "Execution was not successful" — screenshot showed score 20.5 (which matches the LOW demo, not the uploaded protocol), with Gradio's `queue: 1/1 \| 32.7/106.8s` overlay duplicated across the scorecard and PDF panels |
| Test artifact | `/Users/sachinpatel/Downloads/Protocol_Test_Phase1.pdf` (938.7 KB, 73 pages, BVD-523 oncology Phase 1) |
| Reproduction script | `scripts/diagnose_ollama.py <pdf_path>` |
| Verification command | `python scripts/diagnose_ollama.py /Users/sachinpatel/Downloads/Protocol_Test_Phase1.pdf` |

### What actually happened

The Ollama pipeline completed successfully end-to-end on the test PDF using `llama3.1:8b`. All 5 LLM calls returned valid JSON conforming to the expected schemas. Final extracted metrics:

| Metric | Value | Confidence | Citations |
|---|---|---|---|
| `ie_criteria_count` | 12 | 0.90 | 5 |
| `endpoints_count` | 7 | 1.00 | 5 |
| `total_visits` | 10 | 0.90 | 1 |
| `invasive_procedures` | 2 | (n/a) | 0 |

No metric returned zero. The `_empty_result` fallback was never triggered. `_validate_result` passed for every call (no retries needed).

### Per-call latency profile (`llama3.1:8b`, MacBook local CPU)

| Tool call | Latency |
|---|---|
| `classify_sections` | 47.0s |
| `extract_ie_criteria` (Logic Agent) | 164.0s |
| `extract_visit_schedule` (Table Agent) | 176.9s |
| `extract_procedures` (Temporal Agent) | 43.5s |
| `extract_endpoints` | 60.2s |
| **Total wall-clock** | **492s (8.2 min)** |

### Root cause of the perceived failure

Three factors compounded in the user-facing UX:

1. **Long runtime with no informative feedback** — 8 minutes is correct expected behavior for a 73-page protocol on CPU-bound local inference, but the current `build_progress_html` shows only step + percent + elapsed. With no ETA and no pulsing animation, the bar can sit at "Logic Agent: Extracting I/E criteria... 30%" for 2-3 minutes and look hung.
2. **Gradio's default queue progress overlay duplicates across every output component** — the `analyze_btn.click()` handler yields a 13-tuple updating the scorecard, radar, formula, PDF, error, batch verification table, etc. Gradio paints `queue: 1/1 \| 32.7/106.8s` onto each updating component, producing visible duplication across the scorecard and PDF panels (visible in the user's screenshot).
3. **Scorecard still shows the persisted demo value (20.5)** — the user's screenshot was taken mid-run; the new scorecard hasn't yielded yet, so the previously-rendered LOW-demo value is still on screen, making it look like the upload "didn't do anything."

### Resolution

**Phase 1: no Ollama-specific code change required.** The pipeline behaves correctly.

The user-facing fix is delivered in **Phase 4** of the V2.1 polish plan:
- Suppress Gradio's queue overlay via `show_progress="hidden"` on `analyze_btn.click()` so only our custom progress bar renders.
- Add an ETA (`elapsed × (1 - fraction) / fraction`) to `build_progress_html()` so users can see roughly how much longer to wait.
- Add a subtle CSS pulse on the active step so the bar visibly "breathes" even when sitting on a long step.
- Add an Ollama-only pre-flight note in the connection-status pill or above the Analyze button: "Local extraction can take 5–10 minutes on a 70-page protocol — sit tight." This sets the right expectation.

The diagnostic script `scripts/diagnose_ollama.py` is kept in-repo for future regression checks.

**Recommendation**: `Execute now` — proceed directly to Phase 2 (provider restructure). No change to `logic/ai_extractor.py` or `logic/ollama_utils.py` is needed for Phase 1.
