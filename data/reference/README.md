# Canonical reference metadata

These JSON files are the single source of truth for curated dashboard metadata.
Edit them here; the frontend no longer maintains its own copies:

- `investigations.json` — narrative fields, O₂ ranges, theme and phase for the 15 investigations
- `environments.json` — the four habitable places and their O₂ windows
- `theme_weights.json` — pillar weights per environment
- `psi.json` — NASA PSI accession numbers and URL template
- `pillars.json` — pillar definitions, order and fuel phases

`scripts/build-dashboard.mjs` combines these files with the summaries derived from
`data/processed` and writes `../flame-in-freefall/src/data/dashboard.json`. The
frontend `src/data/*.js` modules only re-export slices of that generated artifact.

The backend validates IDs, themes, phases, O₂ windows, PSI coverage and environment
weights at load time. The dashboard build also fails when those ID sets disagree.
