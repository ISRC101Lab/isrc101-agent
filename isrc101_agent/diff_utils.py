"""Diff utilities for file edit preview and unified diff application."""

import difflib
import re
from typing import Optional, Tuple, List


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


def compute_diff_stats(diff_text: str) -> Tuple[int, int, int]:
    """Compute statistics from unified diff.

    Returns: (lines_added, lines_removed, files_changed)
    """
    lines = diff_text.splitlines()
    added = 0
    removed = 0
    files = set()

    for line in lines:
        if line.startswith('+++'):
            # Extract filename
            parts = line.split('\t', 1)
            if parts:
                fname = parts[0][4:].strip()  # Remove '+++ '
                if fname and fname != '/dev/null':
                    files.add(fname)
        elif line.startswith('+') and not line.startswith('+++'):
            added += 1
        elif line.startswith('-') and not line.startswith('---'):
            removed += 1

    return added, removed, len(files)


def get_char_level_diff(old_line: str, new_line: str) -> Tuple[List[Tuple[str, bool]], List[Tuple[str, bool]]]:
    """Compute character-level differences between two lines.

    Returns: (old_parts, new_parts) where each part is (text, is_changed)
    """
    # Use SequenceMatcher for character-level diff
    matcher = difflib.SequenceMatcher(None, old_line, new_line)

    old_parts = []
    new_parts = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # Unchanged text
            old_parts.append((old_line[i1:i2], False))
            new_parts.append((new_line[j1:j2], False))
        elif tag == 'replace':
            # Changed text
            old_parts.append((old_line[i1:i2], True))
            new_parts.append((new_line[j1:j2], True))
        elif tag == 'delete':
            # Text removed from old
            old_parts.append((old_line[i1:i2], True))
        elif tag == 'insert':
            # Text added to new
            new_parts.append((new_line[j1:j2], True))

    return old_parts, new_parts


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
            result.append(f"[#F85149]- {line[2:]}[/#F85149]")
        elif line.startswith('+ '):
            result.append(f"[#57DB9C]+ {line[2:]}[/#57DB9C]")
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
        parts.append(f"[#57DB9C]+{added}[/#57DB9C]")
    if removed:
        parts.append(f"[#F85149]-{removed}[/#F85149]")
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


class DiffApplyError(Exception):
    """Raised when a unified diff cannot be applied."""
    pass


def apply_unified_diff(content: str, diff_text: str) -> str:
    """Apply a unified diff to file content, returning the new content.

    Parses standard unified diff format:
        --- a/file
        +++ b/file
        @@ -start,count +start,count @@
        context / - / + lines

    Raises DiffApplyError if context lines don't match or the diff is malformed.
    """
    lines = content.splitlines(keepends=True)
    # Ensure every line has a newline for consistent matching
    if lines and not lines[-1].endswith('\n'):
        lines[-1] += '\n'
        trailing_newline = False
    else:
        trailing_newline = True if lines else True

    hunks = _parse_hunks(diff_text)
    if not hunks:
        raise DiffApplyError("No hunks found in diff text.")

    # Apply hunks in reverse order (bottom-to-top) to avoid line-shift issues
    for hunk in reversed(hunks):
        lines = _apply_hunk(lines, hunk)

    result = "".join(lines)
    # Preserve original trailing-newline behavior
    if not trailing_newline and result.endswith('\n'):
        result = result[:-1]
    return result


def _parse_hunks(diff_text: str) -> List[dict]:
    """Parse unified diff text into a list of hunk dicts.

    Each hunk: {
        'old_start': int,  # 1-indexed start line in original
        'old_count': int,
        'new_start': int,
        'new_count': int,
        'lines': [(tag, text), ...]  # tag: ' ', '+', '-'
    }
    """
    hunk_header_re = re.compile(
        r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@'
    )
    hunks = []
    current_hunk = None
    in_diff = False

    for raw_line in diff_text.splitlines(keepends=True):
        line = raw_line.rstrip('\n').rstrip('\r')

        # Skip file headers
        if line.startswith('--- ') or line.startswith('+++ '):
            in_diff = True
            continue

        m = hunk_header_re.match(line)
        if m:
            in_diff = True
            if current_hunk is not None:
                hunks.append(current_hunk)
            current_hunk = {
                'old_start': int(m.group(1)),
                'old_count': int(m.group(2)) if m.group(2) is not None else 1,
                'new_start': int(m.group(3)),
                'new_count': int(m.group(4)) if m.group(4) is not None else 1,
                'lines': [],
            }
            continue

        if current_hunk is not None and in_diff:
            if line.startswith('+'):
                current_hunk['lines'].append(('+', line[1:]))
            elif line.startswith('-'):
                current_hunk['lines'].append(('-', line[1:]))
            elif line.startswith(' ') or line == '':
                # Context line (leading space) or empty context line
                text = line[1:] if line.startswith(' ') else ''
                current_hunk['lines'].append((' ', text))
            elif line.startswith('\\'):
                # "\ No newline at end of file" — skip
                continue

    if current_hunk is not None:
        hunks.append(current_hunk)

    return hunks


def _apply_hunk(lines: List[str], hunk: dict) -> List[str]:
    """Apply a single hunk to lines, returning the modified lines list."""
    old_start = hunk['old_start'] - 1  # convert to 0-indexed

    # Build expected old lines and new replacement lines from the hunk
    expected_old = []
    new_lines = []
    for tag, text in hunk['lines']:
        text_with_nl = text + '\n' if not text.endswith('\n') else text
        if tag == ' ':
            expected_old.append(text_with_nl)
            new_lines.append(text_with_nl)
        elif tag == '-':
            expected_old.append(text_with_nl)
        elif tag == '+':
            new_lines.append(text_with_nl)

    # Verify context: expected old lines must match the file content
    for i, exp in enumerate(expected_old):
        file_idx = old_start + i
        if file_idx >= len(lines):
            raise DiffApplyError(
                f"Hunk at line {hunk['old_start']}: file has only {len(lines)} lines, "
                f"but hunk expects content at line {file_idx + 1}."
            )
        actual = lines[file_idx]
        if actual.rstrip('\n') != exp.rstrip('\n'):
            raise DiffApplyError(
                f"Hunk at line {hunk['old_start']}: context mismatch at line {file_idx + 1}.\n"
                f"  Expected: {exp.rstrip()!r}\n"
                f"  Actual:   {actual.rstrip()!r}"
            )

    # Replace the old range with new lines
    lines[old_start:old_start + len(expected_old)] = new_lines
    return lines
