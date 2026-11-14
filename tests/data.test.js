import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { parseCsv } from "../scripts/lib/csv.js";
import { summarizeInvestigation } from "../scripts/lib/summary.js";
import { ADAPTERS } from "../scripts/lib/adapters.js";

const readProcessed = (relativePath) =>
  fs.readFileSync(new URL(`../data/processed/${relativePath}`, import.meta.url), "utf8");

test("parseCsv keeps commas and escaped quotes inside quoted fields", () => {
  const text = 'date,fuel,note\r\n2020-01-01,"ethane, propane","said ""hot"" flame"\r\n';

  const { headers, rows } = parseCsv(text);

  assert.deepEqual(headers, ["date", "fuel", "note"]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].fuel, "ethane, propane");
  assert.equal(rows[0].note, 'said "hot" flame');
});

test("summarizeInvestigation derives count, date, O2, airflow, pressure and fuels", () => {
  const adapter = {
    files: [
      {
        path: "fixture.csv",
        pick: (rows) => ({
          dates: rows.map((r) => r.date),
          o2: rows.map((r) => Number(r.o2)),
          airflow: rows.map((r) => Number(r.flow)),
          pressure: rows.map((r) => Number(r.pressure)),
          fuels: rows.map((r) => r.fuel),
        }),
      },
    ],
    variables: ["o2", "flow", "pressure", "fuel"],
  };
  const text = "date,fuel,o2,flow,pressure\n2020-01-01,methane,21,5,0.5\n2020-02-01,ethylene,30,10,3\n";

  const summary = summarizeInvestigation([text], adapter);

  assert.equal(summary.tests, 2);
  assert.deepEqual(summary.date, { start: "2020-01-01", end: "2020-02-01" });
  assert.deepEqual(summary.o2, { min: 21, max: 30, unit: "%", partial: false });
  assert.deepEqual(summary.airflow, { min: 5, max: 10, unit: "cm/s" });
  assert.deepEqual(summary.pressure, { min: 0.5, max: 3, unit: "atm" });
  assert.deepEqual(summary.fuels, ["ethylene", "methane"]);
  assert.deepEqual(summary.variableProfiles.o2, { kind: "range", min: 21, max: 30, count: 2 });
  assert.deepEqual(summary.variableProfiles.fuel, {
    kind: "categories",
    count: 2,
    values: ["ethylene", "methane"],
  });
});

test("summary for real BASS table counts 121 tests", () => {
  const adapter = ADAPTERS.bass;
  const texts = adapter.files.map((f) => readProcessed(f.path));

  const summary = summarizeInvestigation(texts, adapter);

  assert.equal(summary.tests, 121);
  assert.deepEqual(summary.date, { start: "2012-03-30", end: "2013-06-01" });
  assert.equal(summary.o2, null);
});

test("summary for Saffire counts burns and marks the O2 range as partial", () => {
  const adapter = ADAPTERS.saffire;
  const texts = adapter.files.map((f) => readProcessed(f.path));

  const summary = summarizeInvestigation(texts, adapter);

  assert.equal(summary.tests, 2);
  assert.equal(summary.testLabel, "burns");
  assert.equal(summary.o2.partial, true);
  assert.deepEqual(summary.o2, { min: 21.5, max: 21.7, unit: "%", partial: true });
});
