import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { ADAPTERS } from "./lib/adapters.js";
import { summarizeInvestigation } from "./lib/summary.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DATA_DIR = path.join(ROOT, "data", "processed");

const outIndex = process.argv.indexOf("--out");
if (outIndex !== -1 && !process.argv[outIndex + 1]) {
  throw new Error("--out needs a file path");
}
const OUT_FILE =
  outIndex === -1 ? path.join(ROOT, "generated.json") : path.resolve(process.cwd(), process.argv[outIndex + 1]);

const summaries = {};

for (const [id, adapter] of Object.entries(ADAPTERS)) {
  const texts = adapter.files.map((file) => {
    const filePath = path.join(DATA_DIR, file.path);
    if (!fs.existsSync(filePath)) {
      throw new Error(`missing cleaned table for ${id}: ${filePath}`);
    }
    return fs.readFileSync(filePath, "utf8");
  });
  summaries[id] = summarizeInvestigation(texts, adapter);
}

fs.mkdirSync(path.dirname(OUT_FILE), { recursive: true });
fs.writeFileSync(OUT_FILE, `${JSON.stringify(summaries, null, 2)}\n`);
console.log(
  `wrote ${Object.keys(summaries).length} investigation summaries to ${path.relative(process.cwd(), OUT_FILE)}`
);
