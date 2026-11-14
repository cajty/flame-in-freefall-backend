---
description: Stage changes and create a Conventional Commits commit
argument-hint: "[optional scope or message hint]"
allowed-tools: Read Grep Glob Bash(git status) Bash(git diff *) Bash(git add *) Bash(git commit *)
---

Create one commit for the current changes. $ARGUMENTS is an optional hint for the
scope or message; ignore it if it does not fit the diff.

1. `git status` and `git diff` — review everything that changed.
2. `git add` the files that belong to this one logical change. Do not use `git add -A`.
3. Verify nothing staged is a secret, a credential, or a large binary.
4. Run this project's lint and test commands, as listed in `CLAUDE.md`.
5. Commit with `type(scope): subject` — imperative, lowercase, no trailing period,
   subject at most 72 chars. Add a body explaining WHY when the reason is not obvious.

Never `--no-verify`. Never `--amend` a pushed commit. If the changes are genuinely
two logical changes, make two commits and say so.
