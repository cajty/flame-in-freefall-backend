---
description: Run this project's test suite and fix any failures
argument-hint: "[test path or filter]"
allowed-tools: Read Edit Grep Glob Bash
---

Run the tests for $ARGUMENTS (default: the full suite).

1. Use the command listed in this project's `CLAUDE.md`. If it is not there, read
   the manifest and use the project's own script — never an invented command.
2. Run it. Capture the actual output.
3. For each failure: read the test, read the code under test, and decide whether the
   test or the code is wrong. State which, and why, before changing either.
4. Fix the cause. Never weaken, skip, or delete a test to make the suite pass.
5. Re-run until green.

Report the exact command you ran, the before and after pass-fail counts, and any
failure you could not fix with the reason.
