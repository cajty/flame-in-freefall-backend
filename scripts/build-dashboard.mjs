import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildDashboard } from "./lib/dashboard.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REFERENCE_DIR = path.join(ROOT, "data", "reference");
const DATA_DIR = path.join(ROOT, "data", "processed");

const outIndex = process.argv.indexOf("--out");
if (outIndex === -1 || !process.argv[outIndex + 1]) {
  throw new Error("--out <path> is required");
}
const OUT_FILE = path.resolve(process.cwd(), process.argv[outIndex + 1]);

const dashboard = buildDashboard({ referenceDir: REFERENCE_DIR, dataDir: DATA_DIR });

fs.mkdirSync(path.dirname(OUT_FILE), { recursive: true });
fs.writeFileSync(OUT_FILE, `${JSON.stringify(dashboard, null, 2)}\n`);
console.log(
  `wrote ${dashboard.investigations.length} investigations to ${path.relative(process.cwd(), OUT_FILE)}`
);
