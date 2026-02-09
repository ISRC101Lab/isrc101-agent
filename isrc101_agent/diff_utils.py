"""Diff utilities for file edit preview."""

import difflib
from typing import Optional, Tuple


def generate_unified_diff(
    old_content: str,
    new_content: str,
    filename: str = "file",
    context_lines: int = 3
) -> str:
    """Generate unified diff between old and new content.

    Returns a colored diff string suitable for terminal display.
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    # Ensure last lines have newlines for proper diff
    if old_lines and not old_lines[-1].endswith('\n'):
        old_lines[-1] += '\n'
    if new_lines and not new_lines[-1].endswith('\n'):
        new_lines[-1] += '\n'

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=context_lines
    )

    return "".join(diff)


def generate_side_by_side_diff(
    old_content: str,
    new_content: str,
    width: int = 80
) -> str:
    """Generate side-by-side diff (for smaller changes)."""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()

    differ = difflib.Differ()
    diff = list(differ.compare(old_lines, new_lines))

    result = []
    for line in diff:
        if line.startswith('- '):
            result.append(f"[red]- {line[2:]}[/red]")
        elif line.startswith('+ '):
            result.append(f"[green]+ {line[2:]}[/green]")
        elif line.startswith('? '):
            continue  # Skip hint lines
        else:
            result.append(f"  {line[2:]}")

    return "\n".join(result)


def count_changes(old_content: str, new_content: str) -> Tuple[int, int, int]:
    """Count lines added, removed, and modified.

    Returns: (added, removed, modified)
    """
    old_lines = set(old_content.splitlines())
    new_lines = set(new_content.splitlines())

    removed = len(old_lines - new_lines)
    added = len(new_lines - old_lines)

    return added, removed, 0


def format_diff_summary(added: int, removed: int) -> str:
    """Format a summary of changes."""
    parts = []
    if added:
        parts.append(f"[green]+{added}[/green]")
    if removed:
        parts.append(f"[red]-{removed}[/red]")
    return ", ".join(parts) if parts else "no changes"


def preview_str_replace(
    content: str,
    old_str: str,
    new_str: str,
    filename: str = "file",
    context_lines: int = 3
) -> Optional[str]:
    """Preview a str_replace operation.

    Returns unified diff if old_str is found exactly once, None otherwise.
    """
    count = content.count(old_str)
    if count != 1:
        return None

    new_content = content.replace(old_str, new_str, 1)
    return generate_unified_diff(content, new_content, filename, context_lines)
