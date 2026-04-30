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
