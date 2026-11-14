import fs from "node:fs";
import path from "node:path";
import { ADAPTERS } from "./adapters.js";
import { summarizeInvestigation } from "./summary.js";

const readJson = (dir, name) => JSON.parse(fs.readFileSync(path.join(dir, name), "utf8"));

const GRAVITY_VALUES = new Set(["microgravity", "partial", "ground", "mixed"]);
const ENVIRONMENT_GRAVITY_VALUES = new Set(["microgravity", "partial"]);
const SCALE_VALUES = new Set(["bench", "glovebox", "rack", "spacecraft"]);
const DATA_QUALITY_VALUES = new Set(["measured", "assumed-air", "partial", "planned"]);

const sortedIds = (items) => items.map((item) => item.id).sort();

function sameIds(left, right) {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function summarizeAll(dataDir) {
  const summaries = {};
  for (const [id, adapter] of Object.entries(ADAPTERS)) {
    const texts = adapter.files.map((file) => {
      const filePath = path.join(dataDir, file.path);
      if (!fs.existsSync(filePath)) {
        throw new Error(`missing cleaned table for ${id}: ${filePath}`);
      }
      return fs.readFileSync(filePath, "utf8");
    });
    summaries[id] = summarizeInvestigation(texts, adapter);
  }
  return summaries;
}

// Canonical dashboard data: the reference JSON is the source of truth for curated
// metadata; cleaned tables add the derived summaries. The frontend imports the
// result as one artifact so no narrative content is maintained twice.
export function buildDashboard({ referenceDir, dataDir }) {
  const investigations = readJson(referenceDir, "investigations.json");
  const environments = readJson(referenceDir, "environments.json");
  const themeWeights = readJson(referenceDir, "theme_weights.json");
  const psi = readJson(referenceDir, "psi.json");
  const pillars = readJson(referenceDir, "pillars.json");
  const summaries = summarizeAll(dataDir);

  const investigationIds = sortedIds(investigations);
  if (!sameIds(investigationIds, Object.keys(summaries).sort())) {
    throw new Error("reference investigations and cleaned-table adapters disagree");
  }
  if (!sameIds(investigationIds, Object.keys(psi.ids).sort())) {
    throw new Error("reference investigations and PSI IDs disagree");
  }
  const environmentIds = sortedIds(environments);
  if (!sameIds(environmentIds, Object.keys(themeWeights).sort())) {
    throw new Error("reference environments and theme weights disagree");
  }
  for (const item of investigations) {
    if (!pillars.pillars[item.theme]) {
      throw new Error(`${item.id}: unknown theme ${item.theme}`);
    }
    if (!pillars.phases[item.phase]) {
      throw new Error(`${item.id}: unknown phase ${item.phase}`);
    }
    if (!GRAVITY_VALUES.has(item.gravity)) {
      throw new Error(`${item.id}: unknown gravity ${item.gravity}`);
    }
    if (!SCALE_VALUES.has(item.scale)) {
      throw new Error(`${item.id}: unknown scale ${item.scale}`);
    }
    if (!DATA_QUALITY_VALUES.has(item.dataQuality)) {
      throw new Error(`${item.id}: unknown data quality ${item.dataQuality}`);
    }
  }
  for (const environment of environments) {
    if (!ENVIRONMENT_GRAVITY_VALUES.has(environment.gravity)) {
      throw new Error(`${environment.id}: environment gravity must be microgravity or partial`);
    }
  }

  return { investigations, environments, themeWeights, psi, pillars, summaries };
}
