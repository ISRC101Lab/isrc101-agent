---
name: python-bugfix
description: "Systematic Python debugging: reproduce, isolate, fix, verify. Use when users report tracebacks, failing tests, exceptions, import errors, or unexpected behavior."
---

# Python Bugfix

## When to Activate

- User shares a traceback or error message
- User says something is "broken", "failing", or "not working"
- Test failures, import errors, type errors, runtime exceptions

## Debugging Workflow

1. **Reproduce**: Run the exact command that fails. Record the full traceback.
2. **Read the real error**: Look at the FIRST exception in the chain, not the last wrapper.
3. **Isolate**: Narrow down to the smallest code path that triggers the bug.
4. **Understand before fixing**: Read the surrounding code. Why was it written this way?
5. **Minimal fix**: Change only what's broken. Don't refactor adjacent code.
6. **Verify**: Run the failing command again. Run related tests.

## Common Python Bug Patterns

| Pattern | Symptom | Fix |
|---------|---------|-----|
| Missing `None` check | `AttributeError: 'NoneType'` | Add guard or fix upstream |
| Mutable default arg | State leaks between calls | Use `None` + `if arg is None` |
| Import cycle | `ImportError` / `partially initialized` | Move import to function scope or restructure |
| Path issues | `FileNotFoundError` | Use `Path.resolve()`, check `cwd` |
| Encoding | `UnicodeDecodeError` | Specify `encoding="utf-8"` explicitly |
| Dict key missing | `KeyError` | Use `.get()` or validate input |

## Rules

- Never use bare `except:` — always catch specific exceptions.
- Don't add defensive code everywhere; fix the actual root cause.
- If the fix changes public API behavior, warn the user.
- Include the root cause in your explanation, not just "I changed X to Y".

## Verification Checklist

- Failing command now passes.
- Related tests still pass.
- No new lint/syntax errors introduced.
- Output is readable with clear next steps.
