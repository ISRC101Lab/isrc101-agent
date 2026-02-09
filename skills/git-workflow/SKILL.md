---
name: git-workflow
description: "Smart Git workflow: atomic commits, branch strategy, conflict resolution, and PR preparation. Use when users commit, branch, merge, resolve conflicts, or prepare pull requests."
---

# Git Workflow

## When to Activate

- User asks to commit, push, or create branches
- User mentions merge conflicts or rebasing
- User wants to prepare a PR or review commit history
- User asks about branch strategy or Git best practices

## Commit Rules

1. **Atomic commits**: Each commit does ONE thing. Don't mix refactoring with feature code.
2. **Conventional format**: `<type>(<scope>): <description>`
   - Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`
   - Scope: module or file affected (optional)
   - Description: imperative mood, lowercase, no period
3. **Pre-commit checks**:
   - Run linter/formatter before staging
   - Verify no secrets, credentials, or `.env` files in diff
   - Check for debug prints, TODO hacks, commented-out code
4. **Staging strategy**: Stage by intent, not by file. Use `git add -p` logic.

## Branch Strategy

- `main` — stable, always deployable
- `feat/<name>` — new features, branch from main
- `fix/<name>` — bugfixes, branch from main
- `refactor/<name>` — structural changes, branch from main
- Delete branches after merge. Keep history clean.

## Conflict Resolution

1. Read BOTH sides of the conflict fully before choosing.
2. Never blindly accept "ours" or "theirs" — understand intent.
3. After resolving, run tests to verify no regressions.
4. If conflict is complex, explain the resolution to the user.

## PR Preparation

1. Rebase on latest main before PR.
2. Squash fixup commits, keep meaningful history.
3. Write PR description: **What** changed, **Why**, **How to test**.
4. Self-review the diff before submitting.

## Anti-patterns to Avoid

- `git add .` without reviewing what's staged
- Committing generated files, build artifacts, or node_modules
- Force-pushing to shared branches
- Commit messages like "fix", "update", "wip", "asdf"
