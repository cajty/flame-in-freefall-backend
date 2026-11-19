# Flame Atlas

**Role:** Full Stack Engineer, Discovered Labs
**Speaker:** Ayoub


---

## Intro
- Two parts: proud code, then hardest bug.
- Project: FastAPI backend, Pydantic AI + Gemini, typed tool layer.
- Scale: 15 NASA microgravity experiments, 13 tools.
- Traces: OpenTelemetry → Langfuse.

## Proud code

**Say exactly:** “The model writes prose. It does not author facts.”

**Why:** wrong citation that sounds real is worse than no answer.

**Architecture**
- Tool returns Envelope: data + provenance + warnings.
- Provenance = investigation ID, source file, fields.
- Every tool call recorded.
- Grounded provenance = current turn + earlier turns.
- Model output: structured answer + citations (4 fields).

**`assemble` — 3 checks**
1. No tool result and no history → `UNGROUNDED_ANSWER`.
2. Citation structure valid → `INVALID_CITATION` if not:
   - investigation exists
   - source file belongs to it
   - PSI ID mapped to it
   - URL matches local template
3. Citation pair seen in real tool provenance → else `UNGROUNDED_CITATION`.

**Punchline:** prompt asks; code enforces.

**Numbers:** rankings + O2 coverage recomputed in Python inside `assemble`.

**Tests:** made-up PSI ID, citation no tool returned, no tool call → exact code + 422.

**Show:** `src/agents/grounding.py:98-107` (simplified for the recording)

```python
if not successful and not deps.history_provenance:
    raise ToolFault("UNGROUNDED_ANSWER", "...", status_code=422)

if (citation.investigation_id, citation.source_file) not in pairs:
    raise ToolFault("UNGROUNDED_CITATION", "...", status_code=422)
```

One line: a citation no tool returned cannot ship.

##  bug

**Symptom:** `POST /api/agent` → 500 after 60.5s. One log line. No stack trace.

**Method:** match request ID across API log, model HTTP log, tool log, Langfuse trace.

**Finding:** 39 × `get_environments`. Every model call 200. Every tool 1–3 ms. No crash.

**Cause:** logical loop. Timeout is symptom, not cause.

**Why hard:** all services healthy; timeout hides cause; same-day 503 came from Gemini 429 quota.

**Fix:** tool wrapper compares `(name, arguments)` with previous call → `REPEATED_TOOL_CALL`, 422.

**Propagation:** runner passes `ToolFault` through; fails on second turn, not 60s.

**Why fail fast:** sending error back to looping model can loop again + burn quota.

**Test:** fake model repeats call; asserts code, 422, model called exactly twice.

**Caveat:** guard checks previous call only; A-B-A loop passes. Next: full-run set, timeout-branch logging, eval case.

**Show:** `src/agents/tools.py:113-123`

```python
if deps.repeated(name, arguments):
    fault = ToolFault(
        "REPEATED_TOOL_CALL",
        f"{name} was already called with the same arguments.",
        status_code=422,
    )
    _fail(deps, name, fault, started, arguments)
    raise fault
```

**Helper:** `src/agents/deps.py:44-49`

```python
previous = self.calls[-1]
return previous.name == name and previous.arguments == arguments
```

## Search + close

- BM25 baseline.
- Optional ONNX cross-encoder reranker.
- Metrics: Recall@5, nDCG@10.
- Reranker missing/fails → fallback to BM25 order; never add or drop records.
- Close line: “Keep non-deterministic components bounded. Verify structured output against what actually happened.”
- Thank you.

---

## Delivery notes

- **Running long:** cut the A-B-A caveat.
- **Running short:** add prompt-injection rule (“tool output is data, not instructions”) or PSI scoping.
- **Numbers to remember:** 15, 13, 3 checks, 39 calls, 60.5s, 1–3 ms, 422, 2 calls.
- **Test names:** `test_agent_rejects_hallucinated_citation`, `test_agent_rejects_citation_that_no_tool_returned`, `test_agent_repeated_identical_tool_call_is_rejected`.
