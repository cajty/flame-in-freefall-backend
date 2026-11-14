import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { findMetadataZip, looksLikeZip } from "./lib/psi-metadata.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REFERENCE_DIR = path.join(ROOT, "data", "reference");
const RAW_DIR = path.join(ROOT, "data", "raw", "psi");
const MANIFEST = path.join(REFERENCE_DIR, "psi_metadata_manifest.json");
const PSI_ROOT = "https://psi.nasa.gov";
const USER_AGENT = "flame-atlas-metadata-fetch/1.0 (NASA PSI; local research tool)";
const DELAY_MS = 1000;

const force = process.argv.includes("--force");
const onlyArg = process.argv.find((arg) => arg.startsWith("--only="));
const only = onlyArg ? onlyArg.slice("--only=".length) : null;

const assignment = JSON.parse(
  fs.readFileSync(path.join(REFERENCE_DIR, "psi.json"), "utf8")
);

const targets = Object.entries(assignment.ids).flatMap(([investigationId, psiIds]) =>
  psiIds.map((psiId) => ({ investigationId, psiId }))
);
const selected = only ? targets.filter((item) => item.psiId === only) : targets;
if (selected.length === 0) {
  throw new Error(`No PSI record matches --only=${only}`);
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function loadCached(psiId) {
  const dir = path.join(RAW_DIR, psiId);
  const sourcePath = path.join(dir, "source.json");
  if (!fs.existsSync(sourcePath)) return null;
  try {
    const source = JSON.parse(fs.readFileSync(sourcePath, "utf8"));
    const target = path.join(dir, path.basename(source.fileName));
    if (!fs.existsSync(target)) return null;
    const buffer = fs.readFileSync(target);
    if (!looksLikeZip(buffer)) return null;
    if (source.sha256 && source.sha256 !== sha256(buffer)) return null;
    return { source, buffer };
  } catch {
    return null;
  }
}

async function getJson(url) {
  const response = await fetch(url, {
    headers: { "User-Agent": USER_AGENT, Accept: "application/json" },
    signal: AbortSignal.timeout(120_000),
  });
  if (!response.ok) {
    throw new Error(`GET ${url} returned HTTP ${response.status}`);
  }
  return response.json();
}

async function findMetadataFile(record, recordUrl) {
  let file = findMetadataZip(record);
  let version = null;
  if (!file) {
    const versions = await getJson(`${recordUrl}/versions`);
    for (const entry of versions.versions ?? []) {
      const candidate = findMetadataZip(entry);
      if (candidate) {
        file = candidate;
        version = entry.version ?? null;
        break;
      }
    }
  }
  return { file, version };
}

async function downloadZip(psiId, fileName, version) {
  const downloadUrl =
    `${PSI_ROOT}/geode-py/ws/studies/${encodeURIComponent(psiId)}/download` +
    `?file=${encodeURIComponent(fileName)}&redirect=false` +
    (version === null ? "" : `&version=${encodeURIComponent(version)}`);
  const response = await fetch(downloadUrl, {
    headers: { "User-Agent": USER_AGENT, Accept: "text/plain" },
    signal: AbortSignal.timeout(60_000),
  });
  if (!response.ok) {
    throw new Error(`download endpoint returned HTTP ${response.status}`);
  }
  const presignedUrl = (await response.text()).trim();
  if (!presignedUrl.startsWith("https://")) {
    throw new Error(`download endpoint did not return a presigned URL: ${presignedUrl.slice(0, 120)}`);
  }

  const zipResponse = await fetch(presignedUrl, {
    headers: { "User-Agent": USER_AGENT },
    signal: AbortSignal.timeout(120_000),
  });
  if (!zipResponse.ok) {
    throw new Error(`presigned download returned HTTP ${zipResponse.status}`);
  }
  const buffer = Buffer.from(await zipResponse.arrayBuffer());
  if (!looksLikeZip(buffer)) {
    throw new Error("downloaded file does not have a ZIP signature");
  }
  return buffer;
}

const sha256 = (buffer) => crypto.createHash("sha256").update(buffer).digest("hex");
const manifest = [];
const failures = [];

for (const { investigationId, psiId } of selected) {
  const label = `${psiId} (${investigationId})`;
  if (!force) {
    const cached = loadCached(psiId);
    if (cached) {
      manifest.push(cached.source);
      console.log(`${label}: cached ${path.relative(ROOT, path.join(RAW_DIR, psiId, cached.source.fileName))}`);
      continue;
    }
  }
  try {
    const recordUrl = `${PSI_ROOT}/geode-py/ws/repo/investigations/${psiId}`;
    const record = await getJson(recordUrl);
    const { file, version } = await findMetadataFile(record, recordUrl);
    if (!file) {
      throw new Error("no visible _metadata_ ZIP in the investigation record or its version history");
    }
    if (file.restricted === true) {
      throw new Error(`metadata ZIP is restricted: ${file.file_name}`);
    }

    const fileName = path.basename(file.file_name);
    const dir = path.join(RAW_DIR, psiId);
    const target = path.join(dir, fileName);
    let buffer;
    if (!force && fs.existsSync(target)) {
      buffer = fs.readFileSync(target);
      if (!looksLikeZip(buffer)) {
        throw new Error(`existing file is not a ZIP: ${target}`);
      }
      console.log(`${label}: cached ${path.relative(ROOT, target)}`);
    } else {
      buffer = await downloadZip(psiId, fileName, version);
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(target, buffer);
      console.log(`${label}: downloaded ${path.relative(ROOT, target)}`);
    }

    const source = {
      investigationId,
      psiId,
      fileName,
      version,
      bytes: buffer.length,
      sha256: sha256(buffer),
      fetchedAt: new Date().toISOString(),
      sourcePage: `${PSI_ROOT}/physci/repo/data/investigations/${psiId}`,
      recordUrl,
    };
    fs.writeFileSync(path.join(dir, "source.json"), `${JSON.stringify(source, null, 2)}\n`);
    manifest.push(source);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    failures.push({ investigationId, psiId, message });
    console.error(`${label}: FAILED ${message}`);
  }
  await sleep(DELAY_MS);
}

manifest.sort((a, b) => a.psiId.localeCompare(b.psiId));
fs.mkdirSync(REFERENCE_DIR, { recursive: true });
fs.writeFileSync(MANIFEST, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(
  `wrote ${manifest.length} metadata records to ${path.relative(ROOT, MANIFEST)}`
);

if (failures.length > 0) {
  console.error(`\n${failures.length} record(s) failed:`);
  for (const item of failures) {
    console.error(`- ${item.psiId} (${item.investigationId}): ${item.message}`);
  }
  process.exitCode = 1;
}
