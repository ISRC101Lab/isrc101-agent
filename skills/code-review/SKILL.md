---
name: code-review
description: "Systematic code review for quality, security, and maintainability. Use when users ask to review code, check for bugs, audit security, or validate changes before commit/merge."
---

# Code Review

## When to Activate

- User asks to review code, check quality, or find bugs
- Before committing significant changes
- User mentions security concerns or audit
- User asks "is this code OK?" or similar

## Review Methodology

### Pass 1: Correctness
- Does the code do what it claims?
- Are edge cases handled (null, empty, overflow, concurrent)?
- Are error paths correct (not swallowed, not leaking)?
- Do loops terminate? Are off-by-one errors present?

### Pass 2: Security (OWASP-aware)
- **Injection**: SQL, command, path traversal — is user input sanitized?
- **Auth**: Are permissions checked? Are secrets hardcoded?
- **Data exposure**: Are sensitive fields logged or returned in errors?
- **Dependencies**: Are imports from trusted sources?

### Pass 3: Maintainability
- Is naming clear and consistent?
- Are functions small and single-purpose?
- Is there unnecessary duplication?
- Would a new team member understand this code?

### Pass 4: Performance (only if relevant)
- Are there O(n^2) loops on large data?
- Unnecessary allocations in hot paths?
- Missing caching for repeated expensive calls?

## Output Format

For each issue found, report:
1. **Severity**: critical / warning / suggestion
2. **Location**: file:line
3. **Problem**: what's wrong
4. **Fix**: concrete suggestion

Example:
```
[critical] auth.py:42 — Password compared with == instead of constant-time compare.
  Fix: Use hmac.compare_digest() to prevent timing attacks.
```

## Review Guardrails

- Don't nitpick style if a formatter/linter handles it.
- Focus on logic and behavior, not cosmetics.
- If code is correct but could be clearer, mark as "suggestion" not "critical".
- Always acknowledge what's done well — balanced feedback.
