# scripts/

`lib/` reads the canonical reference JSON in `data/reference/` and the cleaned
tables in `data/processed/`.

- `build-data.mjs` writes backend `generated.json` for the Python API.
- `build-dashboard.mjs` writes the frontend artifact with reference metadata and
  derived summaries in one file.

```bash
npm run data
node scripts/build-dashboard.mjs --out ../flame-in-freefall/src/data/dashboard.json
```

The frontend calls `build-dashboard.mjs` before its own dev, build and preview
commands.

Put your own data-cleaning scripts here too (pandas, notebooks, etc.), one per investigation:

```
scripts/clean_flex2.py     reads data/raw/flex2/...  writes data/processed/flex2/...
scripts/clean_efield.py
```

After a cleaning script writes a new table, add its column mapping to
`data/reference/adapters.json` and run both build scripts. The Python API and the
Node build read the same file.
