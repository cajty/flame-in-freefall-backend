# Flame in Freefall Backend

Data and ingestion layer for the Flame Atlas dashboard, plus the Python read-only
tools and analysis agent. `data/reference` is the canonical source for curated
metadata; the React app consumes the dashboard artifact this project generates.

## Layout

```
flame-in-freefall-backend/
  data/
    raw/                    downloaded PSI files (ignored), one folder per investigation
    raw/psi/<PSI-ID>/       metadata ZIP plus source.json per PSI record
    processed/              cleaned tables used by the build and row-level tools
    eval/                   labeled queries for the optional reranker evaluation
    reference/              canonical dashboard metadata (investigations, environments, PSI, pillars)
    reference/psi_metadata_manifest.json  downloaded metadata checksums and source links
  scripts/
    build-data.mjs          reads data/processed, writes generated.json for the API
    build-dashboard.mjs     combines reference + processed into the frontend dashboard.json
    fetch-psi-metadata.mjs  downloads PSI investigation metadata ZIPs
    fetch_psi_catalog.py    builds the offline PSI investigation catalog
    evaluate_reranker.py    compares BM25 and the reranker on labeled queries
    lib/csv.js              CSV parser
    lib/adapters.js         per-investigation column mapping
    lib/psi-metadata.js     metadata ZIP selection and ZIP validation
    lib/summary.js          counts, ranges, dates and variable profiles
    lib/dashboard.js        canonical artifact builder
  src/
    agents/                 Pydantic AI agent and tool wiring
    api/                    FastAPI app, routes and middleware
    config/                 environment-backed settings
    core/                   CSV/data layer, errors, scoring and exports
    models/                 Pydantic schemas
    prompts/                agent system prompt
    tools/                  read-only tool functions
  tests/                    Node data tests and Python API/tool tests
  generated.json            summary consumed by the Python API
```

## Node data pipeline

```bash
npm run data              # writes generated.json in this folder
npm test                  # parser + summary tests
```

## PSI metadata snapshots

```bash
npm run metadata                        # all 17 PSI records
npm run metadata:extract                # unzip into each record folder
node scripts/fetch-psi-metadata.mjs --only=PSI-102
node scripts/fetch-psi-metadata.mjs --force
```

The fetch script reads `data/reference/psi.json`, finds the `_metadata_` ZIP in
each investigation record or its version history, then writes:

- `data/raw/psi/<PSI-ID>/<metadata>.zip`
- `data/raw/psi/<PSI-ID>/extracted/` — `i_Investigation.txt` and `s_*.txt`
- `data/raw/psi/<PSI-ID>/source.json` — source page, record URL, file name,
  version, size, SHA-256 and fetch time
- `data/reference/psi_metadata_manifest.json` — one entry per downloaded record

It uses one request per second, ignores restricted or invisible files, and
validates the ZIP signature before writing. Extraction rejects absolute paths,
`..` traversal, symlinks, duplicate members and oversized archives. The ZIPs
contain ISA-Tab files such as `i_Investigation.txt`; they do not contain measured
CSV rows. Raw downloads are ignored by git. Do not scrape PSI at application
runtime.

## PSI catalog search

```bash
npm run catalog      # fetch every PSI investigation record into a local index
```

`scripts/fetch_psi_catalog.py` reads the public study list, fetches each
investigation record at one request per second, and writes
`data/reference/psi_catalog.json`. Raw responses are cached in
`data/raw/psi-catalog/` (ignored by git), so a rerun resumes; `--force`
refetches every record. The API reads only the local index; it never calls
psi.nasa.gov at request time.

The `search_psi_catalog` agent tool ranks the index with BM25 over title,
acronym, research area, objective and related metadata. Results outside the 15
curated investigations are metadata-only leads: they carry no cleaned measured
data here and must not be cited as evidence.

### Optional ONNX reranker

BM25 remains the default. A cross-encoder can reorder the top
`FLAME_RERANKER_POOL_SIZE` hits; it never adds or drops records. The model is
loaded with `onnxruntime`, which runs on the AMD OCI shapes used for
`CI.Standard.E5.Flex`; OpenVINO is not used.

Export the model once, outside the running API:

```bash
uv run --with "optimum-onnx[onnxruntime]" optimum-cli export onnx \
  --model cross-encoder/ms-marco-MiniLM-L-6-v2 \
  --task text-classification models/reranker-onnx
uv sync --extra rerank
```

The export writes `model.onnx` and `tokenizer.json` into
`models/reranker-onnx/`. A pre-exported quantized build such as
`Xenova/ms-marco-MiniLM-L-6-v2` (`onnx/model_quantized.onnx` renamed to
`model.onnx`, plus its `tokenizer.json`) also works and is about 23 MB. Then
enable it:

```bash
FLAME_RERANKER_ENABLED=1
FLAME_RERANKER_MODEL_DIR=models/reranker-onnx
FLAME_RERANKER_POOL_SIZE=30
```

Each hit keeps the BM25 `score` and adds `rerankScore`. Hits outside the pool
keep BM25 order after the reranked pool. If the model directory, runtime or
inference fails, the tool logs a warning, returns BM25 order and adds a warning
to the response; the request does not fail. Citations are unaffected because
the reranker only reorders existing records.

### Reranker evaluation

`data/eval/psi_catalog_queries.json` holds 29 queries with graded relevance
labels derived from catalog metadata. The labels are not a fire-safety expert
review. Recheck them when the catalog changes.

```bash
uv run python scripts/evaluate_reranker.py --baseline-only
uv run python scripts/evaluate_reranker.py --model-dir models/reranker-onnx
```

Recall@5 counts only direct matches (grade 2). nDCG@10 uses direct and related
(grade 1) records. The script prints per-query values, means, and how many
queries improved or regressed. Enable the reranker only when the mean improves;
otherwise keep `FLAME_RERANKER_ENABLED=0`.

Generate the file the frontend imports:

```bash
node scripts/build-dashboard.mjs --out ../flame-in-freefall/src/data/dashboard.json
```

The frontend runs this automatically before `dev`, `build` and `preview`. Edit
curated content in `data/reference/*.json`; the frontend `src/data/*.js` modules
only re-export slices of the generated artifact.

## Python backend

Requires Python 3.12. The machine's default `python` may be older; use `uv`.

```bash
uv venv --python 3.12 .venv
uv sync --extra dev
npm run data              # generated.json must exist before starting the API
uv run pytest
uv run uvicorn api.main:app --host 127.0.0.1 --port 8000
```

The API prints Pydantic AI agent and tool spans to the server terminal through
Logfire in local mode (`send_to_logfire=False`); nothing is sent to Logfire.

Local trace UI: start Jaeger, run the API, then open `http://localhost:16686`
and select the `flame-atlas-backend` service.

```bash
docker compose up -d
uv run uvicorn api.main:app --host 127.0.0.1 --port 8000
docker compose down      # stop Jaeger when done
```

The public API is read-only. The agent calls the 13 tools from
`docs/agent-tools.md` directly in Python; the tool wrappers are not exposed as
HTTP endpoints.

- `POST /api/agent` — chat with the Pydantic AI agent; needs `GEMINI_API_KEY`.
  Optional `psiIds` limits tools and citations to those PSI records:
```json
{
  "question": "Compare BASS-II and FLEX-2 oxygen ranges.",
  "conversationId": "test-local-001",
  "psiIds": ["PSI-25"]
}
```
BASS-II maps to `PSI-25`; FLEX-2 becomes out of scope. Unknown or malformed PSI IDs return `404 PSI_NOT_FOUND` or `400 INVALID_REQUEST`. The response reports the applied scope under `data.scope`.

`conversationId` keeps the last 8 turns in memory for 30 idle minutes. History is
per process and is lost on restart; requests without an ID stay stateless. Use an
unguessable ID.
- `GET /api/health`, `/api/schema`, `/api/environments`, `/api/gaps`
- `GET /api/investigations`, `/api/investigations/{id}`
- `GET /api/exports/{id}` — download CSV created by the agent's export tool

Configuration lives in `src/config/__init__.py`; copy `.env.example` to `.env`
for local overrides. The model key is optional: everything except `/api/agent`
works without it. Exports are held in memory for 15 minutes and are per-process.

Removed direct tool endpoints: `POST /api/query`, `/api/compare`, `/api/score`,
`/api/tests/aggregate`, `/api/exports`; `GET /api/investigations/{id}/tests`
and `/api/psi/{id}`. Use the agent instead.

Real, non-mocked agent check (server must be running with a key):

```bash
uv run python scripts/agent_real_test.py
```

It exercises schema, compare, gaps, score, test rows, aggregate, PSI, export, and
PSI scope (single, multi, and empty), validates every citation, downloads the
exported CSV, and writes raw responses under `artifacts/`. Use `--skip-agent` in
`scripts/api_smoke_test.py` for the fast no-key check.

Python reads `generated.json` for summary tools and loads the cleaned CSVs once
through a cached pandas repository for row-level tools. `tests/test_reference.py`
recomputes every summary from the CSVs and compares it with `generated.json`, so
the JavaScript and Python pipelines cannot drift silently.

## Data contract

Each summary carries:

- `files` — cleaned tables used
- `tests` + `testLabel` — row count and what a row means
- `date` — first and last test date
- `o2`, `airflow`, `pressure` — min/max, unit, and whether the O2 range is partial
- `fuels` — unique fuel/material values
- `variables` — columns exposed for comparison
- `variableProfiles` — per variable, numeric min/max or the distinct category list/count, shown in the frontend detail sheet

`data/processed` is the source of truth for these derived fields.
`data/reference/` is the source of truth for narrative fields (objective, fuel
description, conditions, measurements), gravity regime, test scale, data quality,
environments, theme weights, PSI IDs and pillars. `scripts/build-dashboard.mjs` embeds both into the frontend artifact and
fails when investigation, PSI, summary or environment ID sets disagree.

Ranking uses provisional weights: O2 coverage 20%, gravity match 15%, test scale
30%, data quality 20% and pillar 15%. Planned-only investigations score 0.
Calibrate these weights with a fire-safety domain expert before treating a ranking
as a safety decision.

## Remaining backend layers

1. Download job into `data/raw`, with source URL, date and checksum.
2. A row store if the CSVs outgrow in-memory loading; `CsvRepository` is the seam.
3. Authentication/rate limiting for a public deployment (switches exist, off by default).
4. Streaming analysis responses, if the frontend needs them.
