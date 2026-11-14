#!/usr/bin/env node
/**
 * PostToolUse hook (Edit|Write): format the file that was just changed.
 *
 * Contract:
 *   exit 0 — success, or a deliberate no-op
 *   exit 2 — surfaces stderr to Claude. On PostToolUse this does NOT block: the
 *            edit has already happened. It is how a formatter failure gets
 *            reported rather than silently swallowed.
 *   exit 1 — non-blocking error. Never used here.
 *
 * This hook is inert until a formatter exists. That is on purpose: a hook that
 * fails in a project with no formatter installed would break every single edit.
 *
 * The formatter is sniffed from the project manifest. There is no config file to
 * keep in sync.
 */

const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const PROJECT_DIR = process.env.CLAUDE_PROJECT_DIR || process.cwd();

function allow() {
  process.exit(0);
}

function block(message) {
  process.stderr.write(String(message).trim() + '\n');
  process.exit(2);
}

function findUp(startDir, names) {
  let dir = startDir;
  for (;;) {
    for (const name of names) {
      const candidate = path.join(dir, name);
      if (fs.existsSync(candidate)) return { dir, file: candidate, name };
    }
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

/** Returns { bin, args } or null when no formatter is available. */
function resolveFormatter(filePath) {
  const manifest = findUp(path.dirname(filePath), ['package.json', 'pyproject.toml']);
  if (!manifest) return null;

  if (manifest.name === 'package.json') {
    // Run Prettier's own JS entry through the current Node binary rather than
    // the node_modules/.bin shim. Both shim forms are unusable from Node:
    //   - the extensionless `.bin/prettier` is a POSIX shell script (ENOENT on Windows)
    //   - `.bin/prettier.cmd` throws EINVAL, because Node refuses to spawn
    //     .cmd/.bat without a shell since the CVE-2024-27980 hardening
    // Going through the package's declared `bin` entry avoids both, needs no
    // shell, and stays correct across Prettier majors.
    const pkgDir = path.join(manifest.dir, 'node_modules', 'prettier');
    const pkg = readJson(path.join(pkgDir, 'package.json'));
    if (!pkg) return null;

    const binRel = typeof pkg.bin === 'string' ? pkg.bin : pkg.bin?.prettier;
    if (typeof binRel !== 'string') return null;

    const entry = path.join(pkgDir, binRel);
    if (!fs.existsSync(entry)) return null;

    // --ignore-unknown: this hook fires on every Edit and Write, so it sees
    // .py, .toml, Makefile and extensionless files too. Without the flag,
    // Prettier exits non-zero on each of those and the hook reports a spurious
    // formatter failure on files it was never meant to touch.
    return {
      bin: process.execPath,
      args: [entry, '--write', '--ignore-unknown'],
    };
  }

  // pyproject.toml — ruff is the formatter of record if it is configured.
  const pyproject = fs.readFileSync(manifest.file, 'utf8');
  if (!/\[tool\.ruff/.test(pyproject)) return null;
  try {
    execFileSync('ruff', ['--version'], { stdio: 'ignore' });
  } catch {
    return null; // configured but not installed — stay inert
  }
  return { bin: 'ruff', args: ['format'] };
}

let payload = '';
let handled = false;

function run() {
  if (handled) return;
  handled = true;

  let input;
  try {
    input = JSON.parse(payload);
  } catch {
    allow();
  }

  const filePath = input?.tool_input?.file_path;
  if (typeof filePath !== 'string' || filePath.length === 0) allow();
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) allow();

  const abs = path.resolve(filePath);
  const rel = path.relative(PROJECT_DIR, abs);

  // Outside the project, or inside git's own state — not ours to touch.
  if (rel.startsWith('..') || path.isAbsolute(rel)) allow();
  if (rel.split(path.sep).includes('.git')) allow();

  const formatter = resolveFormatter(abs);
  if (!formatter) allow();

  try {
    execFileSync(formatter.bin, [...formatter.args, abs], {
      stdio: ['ignore', 'pipe', 'pipe'],
      timeout: 30_000,
    });
  } catch (err) {
    // A missing binary is not the user's formatting problem. Stay inert.
    if (err.code === 'ENOENT') allow();

    // A formatter that ran and rejected the file is worth telling Claude about.
    // Syntax errors typically land here, which is exactly when it matters.
    block(`formatter failed on ${rel}:\n${err.stderr || err.message}`);
  }

  allow();
}

process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  payload += chunk;
});
process.stdin.on('end', run);
process.stdin.on('error', allow);

// Never hang the edit waiting on a pipe that does not close.
setTimeout(run, 1500).unref();
