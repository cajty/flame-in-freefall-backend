import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { buildDashboard } from "../scripts/lib/dashboard.js";

const REFERENCE_DIR = fileURLToPath(new URL("../data/reference", import.meta.url));
const DATA_DIR = fileURLToPath(new URL("../data/processed", import.meta.url));

const readReference = (name) =>
  JSON.parse(fs.readFileSync(new URL(`../data/reference/${name}`, import.meta.url), "utf8"));

test("dashboard artifact embeds canonical reference metadata", () => {
  const dashboard = buildDashboard({ referenceDir: REFERENCE_DIR, dataDir: DATA_DIR });
  const investigations = readReference("investigations.json");
  const environments = readReference("environments.json");
  const themeWeights = readReference("theme_weights.json");
  const psi = readReference("psi.json");
  const pillars = readReference("pillars.json");

  assert.deepEqual(dashboard.investigations, investigations);
  assert.deepEqual(dashboard.environments, environments);
  assert.deepEqual(dashboard.themeWeights, themeWeights);
  assert.deepEqual(dashboard.psi, psi);
  assert.deepEqual(dashboard.pillars, pillars);
});

test("dashboard artifact has one id set across investigations, PSI and summaries", () => {
  const dashboard = buildDashboard({ referenceDir: REFERENCE_DIR, dataDir: DATA_DIR });
  const ids = dashboard.investigations.map((item) => item.id).sort();

  assert.equal(ids.length, 15);
  assert.deepEqual(Object.keys(dashboard.summaries).sort(), ids);
  assert.deepEqual(Object.keys(dashboard.psi.ids).sort(), ids);
  assert.deepEqual(
    dashboard.environments.map((item) => item.id).sort(),
    Object.keys(dashboard.themeWeights).sort()
  );
});

test("dashboard artifact keeps derived variable profiles", () => {
  const dashboard = buildDashboard({ referenceDir: REFERENCE_DIR, dataDir: DATA_DIR });

  assert.deepEqual(
    dashboard.summaries.bass2.variableProfiles.thickness_mm,
    { kind: "range", min: 0.1, max: 5, count: 42 }
  );
  assert.equal(dashboard.summaries.bass2.variableProfiles.material.kind, "categories");
  assert.equal(dashboard.summaries.flex2.testLabel, "planned fuel cases");
});
