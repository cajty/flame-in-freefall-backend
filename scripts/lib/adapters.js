// Per-investigation mapping from cleaned CSV columns to the summary fields shown in the app.
// The canonical mapping lives in data/reference/adapters.json; this module only
// adapts it to the pick functions consumed by summarizeInvestigation.
//
// Every list of summary values is already normalised: O2 in percent, airflow in
// cm/s, dates as YYYY-MM-DD.

import fs from "node:fs";

const definitions = JSON.parse(
  fs.readFileSync(new URL("../../data/reference/adapters.json", import.meta.url), "utf8"),
);

const values = (rows, key) => rows.map((r) => r[key] ?? "").filter((v) => v !== "");

const nums = (rows, columns) =>
  rows
    .flatMap((r) =>
      columns.map(({ column, scale = 1 }) => {
        const value = r[column];
        return value === "" || value == null ? null : Number(value) * scale;
      }),
    )
    .filter((v) => v != null && Number.isFinite(v));

const pick = (spec = {}) => (rows) => ({
  dates: spec.date ? values(rows, spec.date) : [],
  o2: nums(rows, spec.o2 ?? []),
  airflow: nums(rows, spec.airflow ?? []),
  pressure: nums(rows, spec.pressure ?? []),
  fuels: spec.fuel ? values(rows, spec.fuel) : [],
});

const count = (rule) =>
  rule ? (rows) => rows.filter((row) => row[rule.column] === rule.value).length : undefined;

function adapterFrom(definition) {
  return {
    files: definition.files.map((file) => ({
      path: file.path,
      pick: pick(file.pick),
    })),
    variables: definition.variables,
    testLabel: definition.testLabel,
    pressureUnit: definition.pressureUnit,
    o2Partial: definition.o2Partial ?? false,
    plannedOnly: definition.plannedOnly ?? false,
    count: count(definition.countRule),
  };
}

export const ADAPTERS = Object.fromEntries(
  Object.entries(definitions.adapters).map(([id, definition]) => [
    id,
    adapterFrom(definition),
  ]),
);
