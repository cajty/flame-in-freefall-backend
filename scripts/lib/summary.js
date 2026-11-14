import { parseCsv } from "./csv.js";

const round = (n, digits) => {
  const factor = 10 ** digits;
  return Math.round(n * factor) / factor;
};

export function numericRange(values, digits = 2) {
  const nums = values.map(Number).filter(Number.isFinite);
  if (nums.length === 0) return null;
  return { min: round(Math.min(...nums), digits), max: round(Math.max(...nums), digits) };
}

function unique(values) {
  return [...new Set(values.map((v) => v.trim()).filter(Boolean))].sort();
}

function dateRange(values) {
  const dates = unique(values.filter((v) => /^\d{4}-\d{2}-\d{2}$/.test(v)));
  if (dates.length === 0) return null;
  return { start: dates[0], end: dates[dates.length - 1] };
}

// Summarise how one recorded variable varies across rows: a numeric range when
// every value parses as a number, a short category list when the column is
// discrete, otherwise just a distinct-value count.
function columnProfile(rows, key) {
  const values = rows.map((row) => (row[key] ?? "").trim()).filter(Boolean);
  if (values.length === 0) return null;

  const numbers = values.map(Number).filter(Number.isFinite);
  if (numbers.length === values.length) {
    return {
      kind: "range",
      min: round(Math.min(...numbers), 2),
      max: round(Math.max(...numbers), 2),
      count: numbers.length,
    };
  }

  const categories = unique(values);
  if (categories.length <= 12) {
    return { kind: "categories", count: categories.length, values: categories };
  }
  return { kind: "text", count: categories.length };
}

// adapter.files: [{ path, pick(rows) -> { dates, o2, airflow, pressure, fuels } }]
export function summarizeInvestigation(fileTexts, adapter) {
  if (fileTexts.length !== adapter.files.length) {
    throw new Error(`expected ${adapter.files.length} files, got ${fileTexts.length}`);
  }

  const parsed = adapter.files.map((spec, i) => ({ spec, rows: parseCsv(fileTexts[i]).rows }));
  const allRows = parsed.flatMap((p) => p.rows);
  const picks = parsed.map((p) => p.spec.pick(p.rows));

  const gather = (key) => picks.flatMap((p) => p[key] ?? []);
  const o2 = numericRange(gather("o2"), 1);
  const airflow = numericRange(gather("airflow"), 1);
  const pressure = numericRange(gather("pressure"), 2);

  return {
    files: adapter.files.map((f) => f.path),
    tests: adapter.count ? adapter.count(allRows) : allRows.length,
    testLabel: adapter.testLabel ?? "tests",
    date: dateRange(gather("dates")),
    o2: o2 ? { ...o2, unit: "%", partial: !!adapter.o2Partial } : null,
    airflow: airflow ? { ...airflow, unit: adapter.airflowUnit ?? "cm/s" } : null,
    pressure: pressure ? { ...pressure, unit: adapter.pressureUnit ?? "atm" } : null,
    fuels: unique(gather("fuels")),
    variables: adapter.variables,
    variableProfiles: Object.fromEntries(
      (adapter.variables ?? [])
        .map((key) => [key, columnProfile(allRows, key)])
        .filter(([, profile]) => profile !== null)
    ),
  };
}
