---
name: smart-refactor
description: "Safe, incremental code refactoring with verification at each step. Use when users ask to refactor, restructure, rename, extract, or simplify code while preserving behavior."
---

# Smart Refactor

## When to Activate

- User asks to refactor, clean up, or restructure code
- User wants to extract functions, rename symbols, or reduce duplication
- User says code is "messy", "hard to read", or "needs cleanup"

## Core Principle

**Refactoring changes structure, never behavior.** Every step must be verifiable.

## Workflow

1. **Read first**: Understand the full scope before touching anything.
2. **Identify tests**: Find existing tests that cover the target code.
3. **Run tests before**: Establish green baseline. If no tests, warn the user.
4. **One transform at a time**: Extract, rename, inline, or move — never combine.
5. **Run tests after each step**: Catch regressions immediately.
6. **Stop if tests break**: Fix or revert before continuing.

## Safe Transforms (ordered by risk)

### Low Risk
- **Rename**: Variable, function, class — use search to find all references.
- **Extract function**: Pull repeated logic into a named function.
- **Extract constant**: Replace magic numbers/strings with named constants.
- **Remove dead code**: Delete unreachable or unused code.

### Medium Risk
- **Move function/class**: Relocate to a more logical module. Update all imports.
- **Inline function**: Replace single-use wrapper with its body.
- **Simplify conditional**: Flatten nested if/else, use early returns.

### High Risk (require extra verification)
- **Change interface**: Modify function signatures — check all callers.
- **Split module**: Break large file into smaller ones — verify imports.
- **Replace algorithm**: Swap implementation — needs thorough test coverage.

## Anti-patterns

- Don't refactor and add features in the same change.
- Don't refactor code you don't understand yet.
- Don't create abstractions for single-use code.
- Don't rename things to match personal preference — follow project conventions.
- Don't "clean up" working code that nobody needs to change.

## Deliverable

After refactoring, summarize:
1. What was changed and why
2. Test results (before/after)
3. Any remaining cleanup opportunities (for user to decide)
