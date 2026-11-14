---
description: Review the current diff for correctness, security, and quality issues
argument-hint: "[path or branch]"
allowed-tools: Read Grep Glob Bash(git diff *) Bash(git status) Bash(git log *)
---

Review the changes in $ARGUMENTS (default: the working-tree diff against HEAD).

Read the diff first, then read enough surrounding code to judge it. Report only
findings you can point at a specific line for.

Cover, in this order:
1. Correctness — logic errors, unhandled edge cases, off-by-one, null paths,
   wrong operator, race conditions.
2. Security — injection, unvalidated input, missing authorization, leaked secrets.
3. Error handling — swallowed errors, empty catch, missing timeout or retry bound.
4. Tests — is the new behavior covered? Would the test fail without the change?
5. Consistency — does it match this project's `CLAUDE.md` and surrounding code?

For each finding: file:line, what is wrong, why it matters, the smallest fix.
Do not restate what the code does. Do not praise. If you find nothing, say so
plainly and list what you checked.
