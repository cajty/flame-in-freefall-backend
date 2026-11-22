# Walkthrough: `src/agents/tools.py`

This document explains every part of `src/agents/tools.py`, the layer that connects
the pydantic-ai agent to the deterministic service functions. It covers the role of
each section, how a tool call moves through the file, and how every failure class is
handled.

The file has one job: make thirteen different tools behave the same way at the agent
boundary. Tool-specific logic stays in services. Transport, validation, timeouts,
repeat detection, logging, recording, and error translation live here.

## File map

| Lines | Part | Role |
| --- | --- | --- |
| 1-45 | Imports | Service functions, request models, agent dependencies, error types |
| 47 | `logger` | Shared `flame_atlas.agent` logger |
| 50-51 | `_elapsed_ms` | Monotonic duration in milliseconds |
| 54-55 | `_without_none` | Removes absent optional export fields |
| 58-88 | `_fail` | Builds and records one failure envelope |
| 91-164 | `_execute_tool` | Central execution path for all tools |
| 167-197 | `_export_query` | Builds the nested payload for `export_csv` |
| 200-451 | Tool wrappers | Model-facing signature, description, and input construction |
| 454-468 | `TOOL_FUNCTIONS` | Explicit registration list |
| 471-483 | `build_agent` | Creates the agent, output type, settings, and tool registration |

## 1. Imports (lines 1-45)

The imports reveal the architecture.

- `Agent` and `RunContext` come from pydantic-ai. The file defines tools, not the
  model provider.
- `ValidationError` comes from pydantic. Argument validation is expected and is
  translated into a model-visible error.
- `ToolDeps` carries request-scoped state: app context, timeout, recorded calls,
  scope, and conversation provenance.
- `DomainError` and `ToolFault` are the two error layers. `DomainError` is a service
  failure with no HTTP status. `ToolFault` adds a status code for the API boundary.
- Service functions are imported with aliases such as `schema_tool`, `query_tool`,
  and `catalog_tool`. The alias avoids a name collision with the wrapper of the same
  name.
- Request models such as `SearchInput`, `RunQueryInput`, and
  `PsiCatalogSearchInput` define the real validation rules for each tool.
- `SYSTEM_PROMPT` is the global agent instruction block.
- `run_tool` is the adapter that moves synchronous service code off the event loop
  and applies a timeout.

The import list is also a dependency check. If a tool wrapper references a service
that does not exist, the module fails at import time rather than during a request.

## 2. Helpers (lines 50-55)

### `_elapsed_ms(started)`

Computes elapsed time from a `time.perf_counter()` value and truncates to whole
milliseconds. `perf_counter` is monotonic, so it is safe for durations. It measures
wall-clock wait, including time spent sleeping or blocked inside a worker thread.

### `_without_none(**values)`

Returns only entries whose value is not `None`. It is used by `_export_query` so the
export payload contains only fields the model actually supplied. Without it, optional
export fields would be sent as explicit `null` values and could change service
behavior.

## 3. `_fail` (lines 58-88)

`_fail` is the single failure-envelope builder. Every handled failure goes through
it.

Inputs:

- `deps`: records the call.
- `name`: tool name, used for recording and logs.
- `fault`: a `ToolFault` carrying code, message, and optional details.
- `started`: timer start from `_execute_tool`.
- `arguments`: canonical arguments when they exist. Validation failures pass `None`
  because the request model was never created.
- `level`: log level. Default is `WARNING`; hard failures use `ERROR`.
- `stack`: when true, uses `logger.exception` to capture the active traceback.

Behavior:

1. Computes `duration_ms`.
2. Calls `fault.as_error()`, which produces `{"code", "message"}` and includes
   `"details"` only when details are non-empty.
3. Calls `deps.record(name, error=error, arguments=arguments, duration_ms=...)`.
4. Logs either a full exception with stack or a structured one-line record.
5. Returns `{"ok": False, "error": error}` to the model.

The return value is a normal tool result. The model receives it as data, not as a
crash. That is what allows the model to correct arguments, change query text, or use
an earlier result.

The `stack=True` path must run inside an active exception handler, because
`logger.exception` reads the current exception. `_execute_tool` calls it only from the
unexpected-exception branch.

## 4. `_execute_tool` (lines 91-164)

`_execute_tool` is the spine. Every wrapper calls it, so all thirteen tools share the same
runtime behavior.

### Step 1: read dependencies and start the timer

```python
deps = run_context.deps
started = time.perf_counter()
```

`deps` is a `ToolDeps` instance created once per analysis request in
`src/agents/runner.py`. It holds the app context, per-tool timeout, recorded calls,
request scope, and prior conversation provenance.

### Step 2: build and validate the request model

```python
try:
    request = request_factory()
except ValidationError as error:
    ...
```

The wrapper passes a lambda that constructs the tool's input model. Validation
happens here, inside the tool runtime, even though pydantic-ai has already checked
the model-generated JSON against the function signature. This is deliberate defense
in depth: the wrapper signature is the model contract, the input model is the domain
contract.

On validation failure:

- Each Pydantic error becomes a string of the form
  `field.path: message`.
- The fault code is `INVALID_REQUEST`.
- The model receives field-level details and can retry.
- The recorded call has `arguments=None` because no canonical request exists.

### Step 3: canonicalize arguments

```python
arguments = request.model_dump(by_alias=True) if request is not None else None
```

The canonical form uses camelCase aliases because those are the names the model and
API see. This exact dictionary is used for three things:

1. Repeat detection.
2. Logging.
3. The recorded call.

Using one canonical form prevents two semantically identical calls from looking
different because of alias choice or field order.

No-argument tools pass `lambda: None`, so their canonical arguments are `None`.

### Step 4: repeat guard

`deps.repeated(name, arguments)` scans every call recorded in the current analysis,
not just the previous call. It detects direct loops and alternating loops such as
A, B, A, B.

When a repeat is detected, the fault is `REPEATED_TOOL_CALL` with status 422. The
guard is two-stage:

- First identical repeat: `_fail` records the error and returns it to the model. The
  run continues. The model gets one chance to use the earlier result or ask a
  clarifying question.
- Second identical repeat: `deps.repeated_rejections(name, arguments)` is now greater
  than zero, `_fail` logs at `ERROR`, and `_execute_tool` raises the `ToolFault`. The
  analysis request ends with a 422.

The soft-first behavior avoids killing recoverable cases. The hard-second behavior
bounds loops that would otherwise burn tokens and wall-clock time. Numeric usage
limits remain a separate backstop in the runner.

### Step 5: execute the service

```python
envelope = await run_tool(function, deps.ctx, request, deps.timeout_seconds)
```

`run_tool` in `src/tools/runner.py` does two things:

- Moves the synchronous service function to a worker thread with
  `asyncio.to_thread`, keeping the event loop free.
- Applies `asyncio.wait_for` with the configured tool timeout.

The service functions are synchronous by design. Data loading, BM25 search, CSV
export, and optional ONNX reranking are ordinary blocking calls. A tool wrapper must
not pass an `async def` service to `run_tool`; `to_thread` would return an un-awaited
coroutine.

### Step 6: translate failures

Three handlers follow, in order:

1. `DomainError`: a service-level failure. Its code, message, and details become a
   `ToolFault`. The service does not know about HTTP status codes.
2. `ToolFault`: a failure that already carries a status code. This includes
   `TOOL_TIMEOUT` from `run_tool`, adapter errors from `src/tools/psi.py`, and the
   hard repeat-guard rejection.
3. `Exception`: any unexpected failure. The model receives a generic
   `INTERNAL_ERROR`; the full stack goes to the server log through `_fail(...,
   stack=True)`. Internal details never reach the model.

All three become the same error envelope shape. The run continues for the first,
second, and normally the third case. Only the hard repeat path raises.

Status codes are not included in the model-visible error body. They matter when a
`ToolFault` escapes the agent and is rendered by the API layer. Inside the agent
loop, code and message are the actionable parts.

### Step 7: record success

```python
deps.record(name, envelope=envelope, arguments=arguments, duration_ms=duration_ms)
```

A successful call stores the envelope. `ToolDeps.current_provenance` reads
provenance only from calls whose `ok` property is true. A call is successful only
when it has an envelope and no error. This is the link between tool execution and
answer grounding.

### Step 8: log and return

The INFO log contains tool name, success flag, duration, and canonical arguments.
The return value is `envelope.model_dump(by_alias=True)`, so the model sees the same
camelCase contract as the public API.

## 5. `_export_query` (lines 167-197)

`export_csv` is one model-facing tool with one flat argument list, but the export
service needs a nested query object whose shape depends on `kind`.

`_export_query` maps that:

- `comparison`: `ids` and `metrics`.
- `query`: investigation IDs, filters, metrics, group-by, sort, and limit. Uses
  camelCase keys and drops absent optional fields.
- `score`: environment ID plus optional theme and phase filters.
- `gaps`: optional IDs.

This helper keeps the wrapper declarative. All four export shapes are built in one
testable place instead of a large inline lambda.

## 6. Tool wrappers (lines 200-451)

Each wrapper is deliberately thin. It has four jobs:

1. Define the model-facing signature and defaults.
2. Provide the description the model reads to decide when to use the tool.
3. Build the typed input model.
4. Call `_execute_tool` with the correct service and tool name.

| Wrapper | Line | Role |
| --- | --- | --- |
| `get_schema` | 200 | Returns canonical metrics, units, themes, phases, IDs, coverage, limits. Docstring says to call it first. |
| `search_investigations` | 205 | Text and structured search over the fifteen investigations. |
| `get_investigation` | 236 | Returns one merged investigation record with summary, PSI IDs, URLs, and source files. |
| `get_environments` | 248 | Returns mission environments, O2 windows, pressure, and theme weights. |
| `find_data_gaps` | 255 | Reports missing, partial, and planned-only data. |
| `compare_investigations` | 267 | Compares two to five investigations on canonical metrics. |
| `run_query` | 284 | Aggregates dashboard summary rows across investigations. Docstring routes row-level questions elsewhere. |
| `score_investigations` | 310 | Ranks investigations for an environment. |
| `export_csv` | 328 | Creates a CSV export for query, comparison, score, or gaps results. |
| `query_tests` | 368 | Queries individual measured test rows with filters and pagination. |
| `aggregate_tests` | 403 | Computes count, min, max, mean, median, or p90 over test rows. |
| `get_psi_record` | 430 | Looks up one NASA PSI accession and its investigation mapping. |
| `search_psi_catalog` | 442 | Searches the full PSI metadata catalog. Docstring marks results as metadata-only leads. |

Conventions across the file:

- The tool name string passed to `_execute_tool` matches the Python function name. Logs,
  records, plan output, and repeat detection all depend on that match.
- The docstring is part of the model contract, not internal documentation. Long
  docstrings on `run_query`, `query_tests`, and `search_psi_catalog` exist to steer
  tool choice and evidence interpretation.
- Bounds live in the request models, not in the wrappers. For example,
  `PsiCatalogSearchInput` enforces a 1-200 character query and a 1-50 result limit.
- Defaults are declared on the wrapper signature so the model sees them in the
  generated schema.
- No wrapper performs I/O or business logic.
- No-argument tools use `lambda: None`; `_execute_tool` handles a `None` request.
- `export_csv` is the only wrapper that delegates payload construction, through
  `_export_query`.

## 7. `TOOL_FUNCTIONS` (lines 454-468)

An explicit tuple of the thirteen wrappers. Registration order is fixed and visible.
`tests/test_agent.py::test_test_model_registers_all_thirteen_tools` asserts that all
thirteen are registered and that each records a duration.

There is no discovery-based registration. Adding a tool requires adding the wrapper,
adding its request model, adding the service import, and adding it to this tuple.
That explicitness makes accidental exposure harder.

## 8. `build_agent` (lines 471-483)

```python
def build_agent(model: Any) -> Agent[ToolDeps, AnalysisAnswer]:
```

Creates one agent per analysis request with:

- `output_type=AnalysisAnswer`: structured final answer with `answer`, `citations`,
  and `warnings`.
- `deps_type=ToolDeps`: the dependency container passed to every tool and available
  to the grounding layer.
- `instructions=SYSTEM_PROMPT`: global behavior rules.
- `model_settings=ModelSettings(temperature=0.2, top_p=0.95, max_tokens=4000)`:
  low-variance analysis output.
- `retries=2`: retries for tool and output validation.
- `agent.tool(strict=True)`: tools are registered in strict mode.

The function then loops over `TOOL_FUNCTIONS` and registers each wrapper. It is
called once per analysis request; request-scoped dependencies are passed later, at
`agent.run`, not at construction time.

## 9. Successful tool call, end to end

This example was executed against the repository data.

Model emits:

```text
tool: search_psi_catalog
arguments: {"q": "flame spread oxygen", "limit": 3}
```

Flow:

1. pydantic-ai validates the call against the wrapper schema.
2. `search_psi_catalog` builds `PsiCatalogSearchInput(q=..., limit=3)`.
3. `_execute_tool` validates the input model.
4. Canonical arguments become
   `{"q": "flame spread oxygen", "limit": 3}`.
5. The repeat guard finds no earlier identical call.
6. `run_tool` executes the synchronous catalog service in a worker thread with a
   timeout.
7. The service returns an `Envelope`.
8. `_execute_tool` records the envelope, logs success, and returns the camelCase dump.

Trimmed result received by the model:

```json
{
  "ok": true,
  "data": {
    "query": "flame spread oxygen",
    "items": [
      {
        "psiId": "PSI-25",
        "title": "Burning and Suppression of Solids - II",
        "curated": true,
        "investigationIds": ["bass2"],
        "score": 13.707087,
        "matchedTerms": ["flame", "spread", "oxygen"]
      },
      {
        "psiId": "PSI-26",
        "curated": true,
        "investigationIds": ["bass"],
        "score": 11.692217
      }
    ]
  }
}
```

Warnings returned in the same envelope:

```text
PSI catalog results are metadata only; they do not carry measured data in this project.
1 of 3 returned records are outside the 15 curated investigations; treat them as leads, not evidence.
```

The analysis plan records `search_psi_catalog`. The call is successful, but the
catalog result carries no provenance, so it cannot ground a measured claim. To cite
measurements, the model must call a data-bearing tool such as `get_investigation`,
`query_tests`, or `aggregate_tests`.

## 10. Error handling reference

| Failure | Handled at | Model receives | Run continues? |
| --- | --- | --- | --- |
| Input model validation | `_execute_tool` line 101 | `INVALID_REQUEST` plus field paths | Yes |
| Service `DomainError` | `_execute_tool` line 130 | Original code, message, details | Yes |
| Adapter `ToolFault` | `_execute_tool` line 138 | Original code, message, details | Yes |
| Per-tool timeout | `run_tool`, caught at line 138 | `TOOL_TIMEOUT` | Yes |
| Unexpected exception | `_execute_tool` line 140 | `INTERNAL_ERROR`, generic message | Yes |
| First identical repeat | `_execute_tool` line 113 | `REPEATED_TOOL_CALL` | Yes |
| Second identical repeat | `_execute_tool` line 122 | `REPEATED_TOOL_CALL`, then raised | No, request fails 422 |

### Invalid arguments

Model calls `search_psi_catalog` with an empty query. Verified result:

```json
{
  "ok": false,
  "error": {
    "code": "INVALID_REQUEST",
    "message": "Tool arguments failed validation.",
    "details": ["q: String should have at least 1 character"]
  }
}
```

The model can read the field and the rule, then retry. No exception escapes.

### Unexpected exception

A service raised `KeyError("secret internal detail")`. Verified result:

```json
{
  "ok": false,
  "error": {
    "code": "INTERNAL_ERROR",
    "message": "Tool failed."
  }
}
```

The exception text and traceback stay in the server log. The model receives no
internal detail.

### Per-tool timeout

A slow service with a 0.01 second timeout. Verified result:

```json
{
  "ok": false,
  "error": {
    "code": "TOOL_TIMEOUT",
    "message": "The tool did not finish within the allowed time."
  }
}
```

The analysis run continues with the error result. `asyncio.wait_for` cancels the
await, but the worker thread itself is not forcibly killed. The timeout bounds request
latency, not Python thread lifetime. Services must therefore be short and
side-effect-free.

### Domain failure

A missing catalog file produces a `DomainError` from the service. The PSI adapter in
`src/tools/psi.py` maps it to `ToolFault("PSI_CATALOG_UNAVAILABLE",
status_code=503)`. `_execute_tool` converts it to the common error envelope. The model sees
the code and message; the API layer sees the 503 if the fault escapes.

## 11. Repeat guard in detail

`ToolDeps.repeated` compares tool name and canonical arguments across the full run.
The canonical form is the aliased model dump, so field order does not matter and
absent optional fields do not create false differences.

Verified soft rejection, second `get_environments` call in one run:

```json
{
  "ok": false,
  "error": {
    "code": "REPEATED_TOOL_CALL",
    "message": "get_environments was already called with the same arguments. Use the earlier result, or ask one clarifying question."
  }
}
```

The model then returned a final answer based on the earlier result, and the analysis
succeeded.

Verified hard failure, third identical call:

```text
REPEATED_TOOL_CALL 422
```

The guard catches non-consecutive loops because it scans the entire run, not just the
previous call. Tests cover the three behaviors:

- `tests/test_agent.py::test_agent_repeated_identical_tool_call_is_rejected`
- `tests/test_agent.py::test_agent_repeat_guard_allows_one_self_correction`
- `tests/test_agent.py::test_repeat_guard_detects_non_consecutive_loop`

Operational nuance: a validation failure is recorded with `arguments=None`, and it
never reaches the repeat guard, because the guard runs only after a request model is
successfully built. Two identical invalid calls both return `INVALID_REQUEST` rather
than a repeat error.

## 12. Invariants worth preserving

1. A failed call has no envelope. It cannot contribute provenance and cannot ground a
   final citation.
2. A successful call is recorded exactly once, with canonical arguments and duration.
3. The model sees error codes and messages, never stack traces or internal exception
   text.
4. Tool wrappers contain no business logic. They declare a contract and build a
   request model.
5. All tools pass through `_execute_tool`. Adding a second execution path would bypass
   validation, repeat detection, timeout, logging, and recording.
6. Services passed to `run_tool` must be synchronous.
7. The tool name passed to `_execute_tool` must match the wrapper name. Logs, plan output,
   repeat detection, and tests depend on it.
8. Registration stays explicit in `TOOL_FUNCTIONS`.

## 13. Verification

Commands used while writing this document:

```text
uv run pytest tests/test_agent.py tests/test_psi_catalog.py -q
```

Result: 42 passed.

The success payload, repeat-guard outputs, invalid-argument error, internal-error
error, and timeout error in this document were produced by running the real
`_execute_tool` path and a real agent run against the repository context. They are not
hand-written illustrations.

## 14. Related files

| File | Role |
| --- | --- |
| `src/agents/deps.py` | Per-request dependency container, call records, repeat detection, provenance |
| `src/tools/runner.py` | Thread offload and per-tool timeout |
| `src/core/errors.py` | `DomainError`, `ToolFault`, `ErrorCode`, error body shape |
| `src/models/psi.py` | PSI input and result models, including search bounds |
| `src/tools/psi.py` | PSI adapter and status-code mapping |
| `src/core/services/psi_search.py` | BM25 search, scope filtering, reranking, warnings |
| `src/agents/grounding.py` | Citation validation and evidence-backed answer assembly |
| `src/agents/runner.py` | Agent construction, model call, usage limits, conversation history |
| `tests/test_agent.py` | Scripted agent runs, repeat guard, grounding |
| `tests/test_psi_catalog.py` | PSI search and adapter behavior |
