# Flame Atlas Analysis Agent

Example design for an AI agent that answers questions over the investigation data in
`../flame-in-freefall/src/data` and the cleaned tables in `data/processed`.

Path convention: `src/data` and `src/lib` refer to the frontend at
`../flame-in-freefall`. `data/processed` and the proposed `src/tools`, `src/query`,
`src/export`, `src/agent`, and `src/api` paths refer to this backend.

The agent is an analyst, not an author. It selects investigations, calls deterministic
tools, and explains the result. Every number comes from a tool. Every claim carries a
source.

## Agent contract

System prompt:

```text
You are the Flame Atlas analysis agent.

You answer questions about the 15 NASA PSI microgravity combustion investigations in
this project. Use tools for every number, comparison, and citation. Never calculate
from memory.

Call get_schema before planning a query. Use only the canonical metrics and investigation
IDs it returns. If a request uses an unknown field, say so and ask for a supported one.

State when data is missing, partial, or planned-only. Never present a custom analysis as
a real NASA investigation. Never present a planned test matrix as measured results.

Never write files, edit source, run SQL, or execute code. If the request is ambiguous,
ask one clarifying question.

Cite investigation IDs, source files, and NASA PSI URLs in the answer.
```

## Tool catalog

| Tool | Purpose | Main source |
| --- | --- | --- |
| `get_schema` | Return canonical metrics, enums, units, and data coverage | `generated.json`, `data/reference/pillars.json` |
| `search_investigations` | Find investigations by text, theme, phase, O2, fuel, or data availability | `data/reference/investigations.json`, `generated.json` |
| `get_investigation` | Return one full investigation record with sources | `data/reference/investigations.json`, `generated.json`, `data/reference/psi.json` |
| `run_query` | Filter, group, and aggregate summary rows | `generated.json` |
| `compare_investigations` | Compare two to five investigations on canonical metrics | `generated.json` |
| `get_environments` | Return environment O2 windows and theme weights | `data/reference/environments.json`, `data/reference/theme_weights.json` |
| `score_investigations` | Rank investigations for an environment using existing scoring logic | `src/core/services/scoring.py`, reference metadata |
| `find_data_gaps` | Report missing, partial, or planned-only data | `generated.json` |
| `export_csv` | Write a filtered or comparison result as CSV with provenance | query result |
| `search_psi_catalog` | Find NASA PSI investigations by free text across the full metadata catalog | `data/reference/psi_catalog.json` |

Future tools, only after a row-level CSV loader exists:

| Tool | Purpose | Main source |
| --- | --- | --- |
| `query_tests` | Query individual test rows | `data/processed/*.csv` |
| `aggregate_tests` | Count, min, max, mean, percentile over test rows | `data/processed/*.csv` |
| `get_psi_record` | Fetch NASA PSI metadata for a PSI ID | `data/reference/psi.json`, PSI site |

Do not expose `run_sql`, `run_python`, `run_shell`, `write_file`,
`edit_investigations`, or an unrestricted `fetch_url` tool.

## Common result contract

Every tool returns the same envelope:

```json
{
  "ok": true,
  "data": [],
  "provenance": [
    {
      "investigationId": "bass2",
      "sourceFile": "bass2/BASS-II_clean.csv",
      "fields": ["o2_initial_pct", "air_cm_s_min"]
    }
  ],
  "warnings": [
    "BASS-II pressure is not recorded in the cleaned table."
  ]
}
```

`ok: false` returns an error code and a user-safe message, never a stack trace.

```json
{
  "ok": false,
  "error": {
    "code": "UNKNOWN_METRIC",
    "message": "Unsupported metric: burn_rate. Use get_schema for supported metrics."
  }
}
```

## Tool schema example

Use strict JSON Schema. The server validates every call again before execution.

```json
{
  "name": "compare_investigations",
  "description": "Compare two to five investigations on canonical summary metrics. Returns normalized units and provenance. Use get_schema first.",
  "strict": true,
  "input_schema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["ids", "metrics"],
    "properties": {
      "ids": {
        "type": "array",
        "items": { "type": "string" },
        "minItems": 2,
        "maxItems": 5
      },
      "metrics": {
        "type": "array",
        "items": {
          "type": "string",
          "enum": [
            "o2_pct",
            "pressure_atm",
            "airflow_cm_s",
            "test_count",
            "test_date",
            "fuel"
          ]
        },
        "minItems": 1,
        "maxItems": 6
      },
      "normalizeUnits": {
        "type": "boolean",
        "default": true
      }
    }
  }
}
```

## Example transcript

This example uses real values from `generated.json`.

### User

```text
Compare BASS-II and FLEX-2 oxygen ranges and test counts. Tell me if the comparison is
fair. Export the comparison as CSV.
```

### Agent tool call 1

```json
{
  "name": "get_schema",
  "input": {}
}
```

### Tool result 1

```json
{
  "ok": true,
  "data": {
    "metrics": [
      { "name": "o2_pct", "unit": "%", "min": 0, "max": 100 },
      { "name": "pressure_atm", "unit": "atm", "min": 0 },
      { "name": "airflow_cm_s", "unit": "cm/s", "min": 0 },
      { "name": "test_count", "unit": "count", "min": 0 },
      { "name": "test_date", "unit": "ISO-8601 date" },
      { "name": "fuel", "unit": "text" }
    ],
    "themes": ["prevention", "detection", "suppression", "fundamentals"],
    "phases": ["solid", "liquid", "gas"],
    "investigationIds": [
      "bass", "bass2", "bre", "cfi", "cfig", "cld", "efield", "flex",
      "flex2", "flamedesign", "saffire", "same", "samer", "sflame", "spice"
    ]
  },
  "warnings": []
}
```

### Agent tool call 2

```json
{
  "name": "compare_investigations",
  "input": {
    "ids": ["bass2", "flex2"],
    "metrics": ["o2_pct", "pressure_atm", "airflow_cm_s", "test_count"],
    "normalizeUnits": true
  }
}
```

### Tool result 2

```json
{
  "ok": true,
  "data": [
    {
      "investigationId": "bass2",
      "name": "BASS-II",
      "o2_pct": { "min": 13.6, "max": 22.2 },
      "pressure_atm": null,
      "airflow_cm_s": { "min": 0, "max": 38.5 },
      "test_count": 129,
      "testLabel": "tests"
    },
    {
      "investigationId": "flex2",
      "name": "FLEX-2",
      "o2_pct": { "min": 17, "max": 30 },
      "pressure_atm": { "min": 0.5, "max": 3 },
      "airflow_cm_s": { "min": 0.1, "max": 5 },
      "test_count": 8,
      "testLabel": "planned fuel cases"
    }
  ],
  "provenance": [
    {
      "investigationId": "bass2",
      "sourceFile": "bass2/BASS-II_clean.csv",
      "fields": ["o2_initial_pct", "air_cm_s_min", "air_cm_s_max"]
    },
    {
      "investigationId": "flex2",
      "sourceFile": "flex2/FLEX2_clean.csv",
      "fields": [
        "o2_mole_fraction_levels",
        "pressure_atm_levels",
        "flow_velocity_cm_s_min",
        "flow_velocity_cm_s_max"
      ]
    }
  ],
  "warnings": [
    "BASS-II pressure is not recorded in the cleaned table.",
    "FLEX-2 is a planned test matrix, not measured results."
  ]
}
```

### Agent tool call 3

```json
{
  "name": "find_data_gaps",
  "input": {
    "investigationIds": ["bass2", "flex2"]
  }
}
```

### Tool result 3

```json
{
  "ok": true,
  "data": [
    {
      "investigationId": "bass2",
      "missing": ["pressure"],
      "partial": [],
      "plannedOnly": false
    },
    {
      "investigationId": "flex2",
      "missing": [],
      "partial": [],
      "plannedOnly": true
    }
  ],
  "warnings": []
}
```

### Agent answer

```text
The oxygen ranges overlap from 17.0% to 22.2%.

BASS-II:
- O2: 13.6-22.2%
- Airflow: 0-38.5 cm/s
- Pressure: not recorded
- 129 tests

FLEX-2:
- O2: 17-30%
- Pressure: 0.5-3 atm
- Airflow: 0.1-5 cm/s
- 8 planned fuel cases

The comparison is only partly fair. BASS-II has measured tests; FLEX-2 is a planned test
matrix with no measured results in the cleaned table. Do not treat the test counts as
equivalent evidence. Pressure cannot be compared because BASS-II has no pressure column.

Sources:
- BASS-II: generated.json; bass2/BASS-II_clean.csv; PSI-25
- FLEX-2: generated.json; flex2/FLEX2_clean.csv; PSI-68
```

### Agent tool call 4

```json
{
  "name": "export_csv",
  "input": {
    "query": {
      "kind": "comparison",
      "ids": ["bass2", "flex2"],
      "metrics": ["o2_pct", "pressure_atm", "airflow_cm_s", "test_count"]
    },
    "columns": [
      "investigation_id",
      "name",
      "metric",
      "min",
      "max",
      "unit",
      "source_file",
      "psi_id"
    ]
  }
}
```

### Tool result 4

```json
{
  "ok": true,
  "data": {
    "downloadUrl": "/api/exports/6c2f-bass2-flex2.csv",
    "rowCount": 8,
    "columns": [
      "investigation_id",
      "name",
      "metric",
      "min",
      "max",
      "unit",
      "source_file",
      "psi_id"
    ],
    "expiresInSeconds": 900
  },
  "warnings": [
    "BASS-II pressure row is empty.",
    "FLEX-2 rows are planned values."
  ]
}
```

## Custom analysis object

When the user asks for a comparison or derived view, return an analysis object. Do not
add it to `data/reference/investigations.json`.

```json
{
  "id": "custom-bass2-flex2-o2",
  "type": "analysis",
  "generated": true,
  "verified": false,
  "name": "BASS-II vs FLEX-2 O2",
  "full": "Comparison derived from cleaned tables",
  "theme": "suppression",
  "phase": "liquid",
  "o2": [17, 22.2],
  "o2known": true,
  "hw": "Derived from BASS-II and FLEX-2",
  "obj": "Compare oxygen range, pressure, airflow, and test count.",
  "fuel": "PMMA, SIBAL, Nomex, wax; iso-octane, n-octane, heptane, decane, ethanol, and mixtures",
  "cond": "Derived analysis, not a new experiment. BASS-II measured; FLEX-2 planned matrix.",
  "meas": "O2 range, pressure, airflow, test count",
  "data": {
    "bass2": "generated.json",
    "flex2": "generated.json"
  },
  "source": {
    "files": [
      "generated.json",
      "data/processed/bass2/BASS-II_clean.csv",
      "data/processed/flex2/FLEX2_clean.csv"
    ],
    "fields": ["o2", "pressure", "airflow", "tests", "fuels"],
    "psi": ["PSI-25", "PSI-68"],
    "urls": [
      "https://psi.nasa.gov/physci/repo/data/investigations/PSI-25",
      "https://psi.nasa.gov/physci/repo/data/investigations/PSI-68"
    ]
  }
}
```

## Data rules

- `generated.json` is a summary. It has no individual test rows.
- The source of truth for row-level data is `data/processed/*.csv`.
- `data/reference/investigations.json` is the canonical narrative source. The frontend
  dashboard artifact is generated from it; do not edit `src/data/dashboard.json` by hand.
- Use the merged investigation records. The merge applies generated O2 values only when
  the range is complete, in `scripts/build-dashboard.mjs` and the frontend data module.
- Saffire O2 is partial. The cleaned table covers Saffire-I only. See the partial flag in
  `generated.json`.
- Pressure units differ: CFI-G uses bar, FLEX uses kPa, Flame Design uses atm. Normalize
  to atm before comparison.
- FLEX-2 is a planned matrix. Label it as planned, never as measured.
- BASS, CLD, E-FIELD, SAME, SAME-R, and SPICE have no O2 column. Do not invent an O2
  value. Their UI entries assume air at 21% and mark `o2src: "air"`.

## Answer rules

- State the overlap or difference, not only the raw values.
- State missing data before drawing a conclusion.
- Never compare test counts without checking `testLabel`. A test, a test day, a burn,
  an analysed flame, and a planned fuel case are different units.
- Cite `sourceFile` for every numeric group.
- Cite PSI IDs and URLs from `data/reference/psi.json`.
- Mark generated analysis with `generated: true` and `verified: false`.
- If the data cannot answer the question, say so and list the missing field.

## Server-side validation

The agent does not enforce its own limits. The server validates every tool call.

- Investigation ID must exist.
- Metric must be in the canonical registry.
- Theme must be one of `prevention`, `detection`, `suppression`, `fundamentals`.
- Phase must be one of `solid`, `liquid`, `gas`.
- O2 must be between 0 and 100.
- Pressure must be greater than 0.
- Row limit defaults to 500; maximum 5,000.
- Timeout for a tool call: 5 seconds.
- Export URL expires after 15 minutes.
- CSV cells starting with `=`, `+`, `-`, or `@` are prefixed with a single quote.
- No raw SQL, shell, Python, or file-write tool is exposed.

## Public API endpoints

Base path: `/api`. Public surface is the agent plus a few read-only discovery
endpoints. The agent calls tools directly in Python; tool wrappers are not
exposed as HTTP endpoints. All responses are JSON except the CSV download.

| Agent tool | Public endpoint |
| --- | --- |
| all 13 tools | `POST /api/agent` |
| `get_schema` | `GET /api/schema` |
| `search_investigations` | `GET /api/investigations` |
| `get_investigation` | `GET /api/investigations/:id` |
| `get_environments` | `GET /api/environments` |
| `find_data_gaps` | `GET /api/gaps` |
| `export_csv` download | `GET /api/exports/:id` |

Removed in this implementation: `POST /api/query`, `/api/compare`, `/api/score`,
`/api/tests/aggregate`, `/api/exports`, `GET /api/investigations/:id/tests`, and
`GET /api/psi/:id`. The sections below keep their tool-level request and response
contracts; they are internal tool calls, not public routes.

### Health

`GET /api/health`

```json
{
  "ok": true,
  "data": {
    "status": "ok",
    "generatedAt": "2026-11-13T12:00:00.000Z",
    "investigations": 15,
    "tables": 18
  },
  "warnings": []
}
```

No authentication. Use it for deployment checks. Do not expose filesystem paths.

### Schema

`GET /api/schema`

Returns the canonical metrics, units, enums, investigation IDs, and field coverage.
The agent must call this before planning a query.

```json
{
  "ok": true,
  "data": {
    "metrics": [
      { "name": "o2_pct", "unit": "%", "min": 0, "max": 100 },
      { "name": "pressure_atm", "unit": "atm", "min": 0 },
      { "name": "airflow_cm_s", "unit": "cm/s", "min": 0 },
      { "name": "test_count", "unit": "count", "min": 0 },
      { "name": "test_date", "unit": "ISO-8601 date" },
      { "name": "fuel", "unit": "text" }
    ],
    "themes": ["prevention", "detection", "suppression", "fundamentals"],
    "phases": ["solid", "liquid", "gas"],
    "investigationIds": [
      "bass", "bass2", "bre", "cfi", "cfig", "cld", "efield", "flex",
      "flex2", "flamedesign", "saffire", "same", "samer", "sflame", "spice"
    ],
    "coverage": {
      "bass2": { "o2_pct": true, "pressure_atm": false, "airflow_cm_s": true }
    }
  },
  "warnings": []
}
```

Cache for five minutes. Add `generatedAt` so the client can detect stale data.

### Investigations

`GET /api/investigations`

Query parameters:

- `q` — text search over `name`, `full`, `obj`, `fuel`, `cond`, `meas`
- `theme` — one of the four pillar keys
- `phase` — `solid`, `liquid`, or `gas`
- `o2Min`, `o2Max` — numeric, 0-100
- `fuel` — case-insensitive text match
- `hasData` — `true` or `false`
- `limit` — default 50, maximum 200
- `offset` — default 0

Response:

```json
{
  "ok": true,
  "data": {
    "items": [],
    "total": 15,
    "limit": 50,
    "offset": 0
  },
  "warnings": []
}
```

`GET /api/investigations/:id`

Returns one merged investigation record, its generated summary, PSI IDs, PSI URLs, and
source files.

```json
{
  "ok": true,
  "data": {
    "id": "bass2",
    "name": "BASS-II",
    "theme": "prevention",
    "phase": "solid",
    "o2": [13.6, 22.2],
    "data": {},
    "psi": {
      "ids": ["PSI-25"],
      "urls": ["https://psi.nasa.gov/physci/repo/data/investigations/PSI-25"]
    },
    "sourceFiles": ["bass2/BASS-II_clean.csv"]
  },
  "warnings": []
}
```

Unknown ID returns `404` with `INVESTIGATION_NOT_FOUND`.

### Environments

`GET /api/environments`

Returns the four environments, their O2 windows, pressure, and theme weights.

```json
{
  "ok": true,
  "data": {
    "items": [
      {
        "id": "moon",
        "name": "Lunar base",
        "o2": [30, 40],
        "psi": "≤ 10.2 psi",
        "themeWeights": {
          "prevention": 30,
          "detection": 18,
          "suppression": 22,
          "fundamentals": 8
        }
      }
    ]
  },
  "warnings": []
}
```

### Query tool (internal)

Tool: `run_query`. Not exposed as a public HTTP endpoint.

Summary-level query. The response states `scope: "summary"`.

Request:

```json
{
  "investigationIds": ["bass2", "flex2"],
  "filters": [
    { "metric": "o2_pct", "op": "between", "min": 17, "max": 22 }
  ],
  "metrics": ["o2_pct", "pressure_atm", "airflow_cm_s", "test_count"],
  "groupBy": ["investigation_id"],
  "sort": [{ "metric": "test_count", "dir": "desc" }],
  "limit": 100
}
```

Allowed operators: `eq`, `neq`, `lt`, `lte`, `gt`, `gte`, `between`, `in`.

Response:

```json
{
  "ok": true,
  "data": {
    "scope": "summary",
    "rows": [],
    "rowCount": 0
  },
  "provenance": [],
  "warnings": ["BASS-II pressure is not recorded."]
}
```

Reject unknown metrics, unknown investigation IDs, invalid ranges, and limits above
5,000 with `400 INVALID_QUERY`.

### Compare tool (internal)

Tool: `compare_investigations`. Not exposed as a public HTTP endpoint.

Request:

```json
{
  "ids": ["bass2", "flex2"],
  "metrics": ["o2_pct", "pressure_atm", "airflow_cm_s", "test_count"],
  "normalizeUnits": true
}
```

Rules:

- Minimum 2 IDs, maximum 5.
- Normalize pressure to atm before comparison.
- Return `testLabel` with every count.
- Return warnings for missing, partial, or planned-only data.

Response uses the common envelope with one object per investigation.

### Score tool (internal)

Tool: `score_investigations`. Not exposed as a public HTTP endpoint.

Request:

```json
{
  "environmentId": "moon",
  "filters": {
    "theme": "prevention"
  }
}
```

Response:

```json
{
  "ok": true,
  "data": {
    "environmentId": "moon",
    "weights": {
      "prevention": 30,
      "detection": 18,
      "suppression": 22,
      "fundamentals": 8
    },
    "items": [
      {
        "investigationId": "cfig",
        "score": 100,
        "o2Overlap": 1,
        "themeWeight": 30
      }
    ]
  },
  "warnings": []
}
```

The scoring formula is ported from the frontend `src/lib/scoring.js` into
`src/core/services/scoring.py`. Tests cover the known values and order;
the endpoint must not invent a different formula.

### Data gaps

`GET /api/gaps?ids=bass2,flex2`

If `ids` is omitted, return all investigations.

```json
{
  "ok": true,
  "data": {
    "items": [
      {
        "investigationId": "bass2",
        "missing": ["pressure"],
        "partial": [],
        "plannedOnly": false
      },
      {
        "investigationId": "flex2",
        "missing": [],
        "partial": [],
        "plannedOnly": true
      }
    ]
  },
  "warnings": []
}
```

### CSV export tool (internal)

Tool: `export_csv`. The agent creates the export; the only public route is
`GET /api/exports/:id` for download.

Request:

```json
{
  "kind": "comparison",
  "query": {
    "ids": ["bass2", "flex2"],
    "metrics": ["o2_pct", "pressure_atm", "airflow_cm_s", "test_count"]
  },
  "columns": [
    "investigation_id",
    "name",
    "metric",
    "min",
    "max",
    "unit",
    "source_file",
    "psi_id"
  ]
}
```

Allowed `kind` values: `query`, `comparison`, `score`, `gaps`.

Response `201 Created`:

```json
{
  "ok": true,
  "data": {
    "exportId": "6c2f8b1a",
    "downloadUrl": "/api/exports/6c2f8b1a",
    "rowCount": 8,
    "columns": ["investigation_id", "name", "metric", "min", "max", "unit", "source_file", "psi_id"],
    "expiresAt": "2026-11-13T12:15:00.000Z"
  },
  "warnings": ["FLEX-2 rows are planned values."]
}
```

`GET /api/exports/:id`

Returns `text/csv; charset=utf-8`.

Required headers:

```text
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="flame-atlas-export-6c2f8b1a.csv"
Cache-Control: no-store
```

Rules:

- Export ID is server-generated. Never use a user-supplied filename.
- Maximum 10,000 data rows.
- Expire after 15 minutes.
- Prefix cells starting with `=`, `+`, `-`, or `@` with a single quote.
- Include `source_file` and `psi_id` columns.
- Expired exports return `410 EXPORT_EXPIRED`.

### Agent endpoint

`POST /api/agent`

This is the only agent endpoint. The frontend asks questions here; the agent calls
the tools above in Python. `conversationId` keeps the last eight turns in an
in-memory store for 30 idle minutes. History is per process and is lost on restart.
Use an unguessable ID. Requests without `conversationId` are stateless.

Request:

```json
{
  "question": "Compare BASS-II and FLEX-2 oxygen ranges and test counts.",
  "conversationId": "optional-client-id",
  "psiIds": ["PSI-25", "PSI-68"],
  "environmentId": "iss",
  "o2": 30
}
```

`psiIds` is optional. When present, the server maps each PSI ID to its
investigation and restricts every tool and every accepted citation to those
investigations. Unknown IDs return `404 PSI_NOT_FOUND`; malformed IDs return
`400 INVALID_REQUEST`. The applied scope is returned in `data.scope`.

`environmentId` is optional. When present the response gains `data.ranking`,
computed with the dashboard formula (`70 × O₂ overlap + theme weight`, ranked
by score then name). `o2` (0–100) is optional and adds `data.covers` — the
investigation IDs whose O₂ range contains the probe — plus `data.reach`, its
count. Both are computed from the catalog, independently of the model answer.
An unknown `environmentId` returns `404 ENVIRONMENT_NOT_FOUND`.

Response:

```json
{
  "ok": true,
  "data": {
    "answer": "The oxygen ranges overlap from 17.0% to 22.2%...",
    "plan": {
      "tools": ["get_schema", "compare_investigations", "find_data_gaps"]
    },
    "citations": [
      {
        "investigationId": "bass2",
        "sourceFile": "bass2/BASS-II_clean.csv",
        "psiId": "PSI-25",
        "url": "https://psi.nasa.gov/physci/repo/data/investigations/PSI-25"
      }
    ],
    "warnings": [
      "BASS-II pressure is not recorded.",
      "FLEX-2 is a planned test matrix."
    ],
    "generated": {
      "bass2": {
        "files": ["bass2/BASS-II_clean.csv"],
        "tests": 129,
        "testLabel": "tests",
        "date": {"start": "2014-02-14", "end": "2016-02-26"},
        "o2": {"min": 13.6, "max": 22.2, "unit": "%", "partial": false},
        "airflow": {"min": 0, "max": 38.5, "unit": "cm/s"},
        "pressure": null,
        "fuels": ["Nomex", "PMMA", "SIBAL", "unspecified", "wax"],
        "variables": ["material", "geometry", "thickness_mm", "size_cm", "air_cm_s_min", "air_cm_s_max", "o2_initial_pct"]
      }
    },
    "ranking": [
      {
        "investigationId": "flex2",
        "name": "FLEX-2",
        "score": 95,
        "o2Overlap": 1.0,
        "themeWeight": 25,
        "o2": [17.0, 30.0],
        "theme": "suppression",
        "phase": "liquid",
        "sourceFiles": ["flex2/FLEX2_clean.csv"],
        "psiIds": ["PSI-68"],
        "psiUrls": ["https://psi.nasa.gov/physci/repo/data/investigations/PSI-68"]
      },
      {
        "investigationId": "bass2",
        "name": "BASS-II",
        "score": 41,
        "o2Overlap": 0.3,
        "themeWeight": 20,
        "o2": [13.6, 22.2],
        "theme": "prevention",
        "phase": "solid",
        "sourceFiles": ["bass2/BASS-II_clean.csv"],
        "psiIds": ["PSI-25"],
        "psiUrls": ["https://psi.nasa.gov/physci/repo/data/investigations/PSI-25"]
      }
    ],
    "covers": ["flex2"],
    "reach": 1,
    "download": null,
    "scope": {
      "psiIds": ["PSI-25", "PSI-68"],
      "investigationIds": ["bass2", "flex2"]
    }
  },
  "warnings": []
}
```

`data.generated` repeats the parsed `generated.json` summaries keyed by
investigation ID. Because this example is scoped to `PSI-25` and `PSI-68`,
`generated`, `ranking` and `covers` contain only `bass2` and `flex2`. Without
`psiIds`, a live response contains all 15. `ranking` and `covers` are null
unless `environmentId` or `o2` is supplied.

Streaming is not implemented.

Rules:

- Authenticate this endpoint if it is publicly reachable.
- Rate-limit by user or IP.
- Cap question length at 2,000 characters.
- Server-side API key only. Never expose the model key to the frontend.
- Do not log full questions by default. Log request ID, status, latency, and token usage.
- If the agent calls no tool, return `422 UNGROUNDED_ANSWER` instead of an answer,
  unless the conversation already contains grounded tool provenance.
- Reject citations that no tool result in the conversation backs with
  `422 UNGROUNDED_CITATION`.

### Saved custom analyses (optional)

Only add these endpoints if custom analyses must survive a page reload. They are writes,
so they require authentication and persistence. The current CSV-only backend has no
database.

`POST /api/analyses`

Request body is the custom analysis object from the section above. The server sets `id`,
`createdAt`, `generated: true`, and `verified: false`; it must not trust those fields from
the client.

```json
{
  "ok": true,
  "data": {
    "id": "custom-bass2-flex2-o2",
    "type": "analysis",
    "generated": true,
    "verified": false,
    "createdAt": "2026-11-13T12:00:00.000Z"
  },
  "warnings": ["Custom analysis is unverified."]
}
```

`GET /api/analyses/:id`

Returns one saved analysis and its `source` object. Unknown ID returns `404`.

`GET /api/analyses?limit=20&offset=0`

Returns the authenticated user's saved analyses. Limit defaults to 20, maximum 100.

`DELETE /api/analyses/:id`

Deletes one saved analysis owned by the authenticated user. Return `204 No Content`.

Rules:

- Require authentication.
- Scope every read and delete to the owner.
- Do not allow a custom analysis ID to collide with a real investigation ID.
- Validate `theme` and `phase` against the schema.
- Reject unsupported metrics or missing `source`.
- Never merge saved analyses into `INVESTIGATIONS`.

### Row-level tools (internal)

Tool: `query_tests` and `aggregate_tests`. Not exposed as public HTTP endpoints.
They read `data/processed/*.csv` through the cached loader.

Tool request for `query_tests`

Query parameters: `metric`, `min`, `max`, `fuel`, `dateStart`, `dateEnd`, `limit`,
`offset`, `cursor`.

Response rows include `rowIndex`, `sourceFile`, and selected columns.

Tool request for `aggregate_tests`:

```json
{
  "investigationId": "bass2",
  "metric": "o2_initial_pct",
  "groupBy": ["material"],
  "stat": "mean"
}
```

Allowed stats: `count`, `min`, `max`, `mean`, `median`, `p90`.

### PSI tool (internal)

Tool: `get_psi_record`. Not exposed as a public HTTP endpoint.

Validate ID with `^PSI-\d+$`. Return the local PSI reference and investigation
mapping. No external fetch is configured; the agent cannot fetch arbitrary URLs.

### PSI catalog search tool (internal)

Tool: `search_psi_catalog`. Not exposed as a public HTTP endpoint.

Free-text BM25 search over `data/reference/psi_catalog.json`, built offline by
`scripts/fetch_psi_catalog.py`. The script reads the public study list and each
investigation record; the API never calls psi.nasa.gov at request time.

Request:

```json
{ "q": "flame spread low oxygen", "limit": 10 }
```

`limit` is 1-50, default 10. Each item carries `psiId`, `title`, `acronym`,
`researchArea`, `subResearchArea`, `snippet`, `url`, `curated`,
`investigationIds`, `restricted`, `score`, `matchedTerms` and `modifiedDate`.

`curated` is true only for PSI IDs mapped in `data/reference/psi.json`. Every
other record is a metadata-only lead: it has no cleaned measured data in this
project and must not be cited as evidence. When the request carries `psiIds`,
results are limited to those mapped investigations.

### Response envelope

All JSON endpoints return:

```json
{
  "ok": true,
  "data": {},
  "provenance": [],
  "warnings": []
}
```

Errors:

```json
{
  "ok": false,
  "error": {
    "code": "INVALID_QUERY",
    "message": "Unsupported metric: burn_rate. Use GET /api/schema.",
    "details": []
  }
}
```

Do not return stack traces, SQL, file paths, or model provider errors to the client.

### Status codes

| Code | Meaning |
| --- | --- |
| 200 | Success |
| 201 | Export created |
| 400 | Invalid input or query |
| 404 | Unknown investigation or export |
| 410 | Export expired |
| 413 | Request or export too large |
| 422 | Valid request, but no grounded answer |
| 429 | Rate limit |
| 500 | Internal error |

### Limits

- JSON body: 64 KB.
- `GET /api/investigations` limit: 200.
- `run_query` result limit: 5,000.
- `compare_investigations` IDs: 5.
- `export_csv` rows: 10,000.
- `POST /api/agent` question: 2,000 characters.
- Tool timeout: 5 seconds.
- Agent request timeout: 60 seconds.
- Export TTL: 15 minutes.
- Conversation history: last 8 turns, 30-minute idle TTL, in memory only.

### Security

- Allow only the frontend origin in CORS.
- Read-only endpoints need no auth for local demo. Public deployment needs auth or a
  gateway rate limit.
- Require auth or a signed client token for `POST /api/agent` because it spends money.
- Keep the model provider key on the server.
- Validate all input at the boundary.
- No raw SQL, shell, Python, or file-write endpoint.
- Escape CSV formula injection.
- Use unguessable export IDs and expiry.
- Log request ID, endpoint, status, latency, and token usage. Do not log secrets or full
  user questions.

## Implementation map

The implemented backend is Python. The Node build scripts produce `generated.json`
for the API and `src/data/dashboard.json` for the frontend from the same canonical
reference files.

| Concern | Implemented path |
| --- | --- |
| Tool handlers | `src/tools/*.py` |
| Canonical metric registry | `src/core/data/registry.py` |
| Summary query engine | `src/tools/query.py`, `src/core/query_filters.py` |
| Row queries and aggregates | `src/tools/rows.py`, `src/core/data/loader.py` |
| CSV export | `src/tools/exports.py`, `src/core/services/exports.py` |
| Agent prompt | `src/prompts/__init__.py` |
| Tool schema and agent wiring | `src/agents/tools.py` |
| Grounding and citations | `src/agents/grounding.py` |
| API routes | `src/api/routes.py`, `src/api/app.py` |
| Tests | `tests/` (pytest) |

## Build order

All thirteen tools are implemented in this repository:

1. `get_schema`, `search_investigations`, `get_investigation`, `get_environments`.
2. `find_data_gaps` and answer rules.
3. `compare_investigations` with unit normalization.
4. `run_query` and `score_investigations`.
5. `export_csv` with provenance and formula escaping.
6. `query_tests` and `aggregate_tests` using the cached pandas CSV loader.
7. `get_psi_record` returns local PSI references only; no external fetch.
8. Custom analysis persistence and streaming remain out of scope.

## Effort

- Tool layer for summary data: 5-8 working days.
- Query, compare, export hardening: 3-5 more days.
- Row-level tools and citation: 7-10 more days.
- Chat UI with plan preview, table, and download: 1-2 weeks.
- Drafting new real investigations: 7-10 days plus human review; not a runtime feature.

## First version

Ship six tools first:

```text
get_schema
search_investigations
get_investigation
get_environments
find_data_gaps
compare_investigations
```

This supports useful, safe questions without row-level data:

- "Which investigations tested above 30% O2?"
- "Compare BASS-II and FLEX-2."
- "Which investigation matters most for a lunar base?"
- "What data is missing for Mars?"
- "Explain why FLEX ranks for suppression."
