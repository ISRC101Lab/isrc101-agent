"""Terminal rendering and user confirmation logic."""

import re
import shutil
from pathlib import Path
from typing import List, Dict, Optional
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.syntax import Syntax
from rich.table import Table
from rich.live import Live
from rich.tree import Tree

from .theme import (
    ACCENT, BORDER, DIM, TEXT, MUTED, SEPARATOR,
    SUCCESS, WARN, ERROR, INFO,
    AGENT_BORDER, AGENT_LABEL, TOOL_BORDER,
)

__all__ = [
    "AGENT_BORDER", "AGENT_LABEL", "TOOL_BORDER",
    "render_error", "render_tool_call", "render_result",
    "render_write_diff", "render_assistant_message",
    "inject_error_hint", "build_diff_panel",
    "show_edit_preview", "show_write_preview",
    "confirm_tool", "handle_image_result",
    "get_adaptive_truncate_limit", "render_parallel_tools",
    "render_file_tree", "get_icon",
]


# ── Icon mapping for Unicode/ASCII fallback ──

# Global flag to control Unicode vs ASCII (set by main.py from config)
_USE_UNICODE = True

def set_use_unicode(enabled: bool):
    """Set whether to use Unicode icons (True) or ASCII fallback (False)."""
    global _USE_UNICODE
    _USE_UNICODE = enabled

# Icon mapping: Unicode → ASCII
_ICON_MAP = {
    "✓": "[OK]",
    "✕": "[X]",
    "◆": "[+]",
    "✎": "[~]",
    "▸": ">",
    "≡": "=",
    "⊙": "@",
    "$": "$",
    "◎": "O",
    "💭": "[THINK]",
    "○": "o",
    "◉": "*",
    "✗": "[X]",
    "·": ".",
    "●": "*",
    "›": ">",
    "⋯": "...",
    "–": "-",
    "▣": "[#]",
}

def get_icon(unicode_icon: str) -> str:
    """Get icon based on Unicode setting.

    Args:
        unicode_icon: The Unicode icon character

    Returns:
        Either the Unicode icon (if enabled) or ASCII fallback
    """
    if _USE_UNICODE:
        return unicode_icon
    return _ICON_MAP.get(unicode_icon, unicode_icon)


# ── Code block parsing for syntax highlighting ──

# Pattern to match fenced code blocks: ```language\ncode\n```


# ── Markdown stripping for plain text output ──

_MD_BOLD_RE = re.compile(r'\*\*(.+?)\*\*')
_MD_ITALIC_RE = re.compile(r'(?<!\*)\*([^*\n]+?)\*(?!\*)')
_MD_INLINE_CODE_RE = re.compile(r'`([^`\n]+?)`')
_MD_HEADER_RE = re.compile(r'^#{1,6}\s+', re.MULTILINE)
_MD_BLOCKQUOTE_RE = re.compile(r'^>\s?', re.MULTILINE)
_MD_FENCE_RE = re.compile(r'^```\w*\s*$', re.MULTILINE)
_MD_HR_RE = re.compile(r'^---+\s*$', re.MULTILINE)
_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\([^)]+\)')


def strip_markdown(text: str) -> str:
    """Strip common markdown formatting from text, keeping content."""
    text = _MD_BOLD_RE.sub(r'\1', text)
    text = _MD_ITALIC_RE.sub(r'\1', text)
    text = _MD_INLINE_CODE_RE.sub(r'\1', text)
    text = _MD_HEADER_RE.sub('', text)
    text = _MD_BLOCKQUOTE_RE.sub('', text)
    text = _MD_FENCE_RE.sub('', text)
    text = _MD_HR_RE.sub('', text)
    text = _MD_LINK_RE.sub(r'\1', text)
    return text



# ── Adaptive truncation based on terminal size ──

def get_adaptive_truncate_limit(truncation_mode: str = "auto",
                                 percentage: float = 0.4,
                                 min_lines: int = 20) -> int:
    """Calculate adaptive truncate limit based on terminal size.

    Args:
        truncation_mode: "auto", "fixed", or "none"
        percentage: Percentage of terminal height to use (0.4 = 40%)
        min_lines: Minimum lines to show (avoid over-truncation on small terminals)

    Returns:
        Number of lines to show, or -1 for no truncation
    """
    if truncation_mode == "none":
        return -1

    if truncation_mode == "fixed":
        return 20

    # Auto mode: calculate based on terminal height
    try:
        terminal_size = shutil.get_terminal_size()
        height = terminal_size.lines
        calculated = int(height * percentage)
        return max(calculated, min_lines)
    except Exception:
        # Fallback to fixed if terminal size detection fails
        return 20


def render_file_tree(
    console: Console,
    file_operations: List[Dict[str, str]],
    title: str = "File Operations"
) -> None:
    """Render a tree view of file operations.

    Args:
        console: Rich console instance
        file_operations: List of dicts with keys: 'path', 'status'
            status can be: 'modified', 'created', 'deleted', 'unchanged'
        title: Tree root title

    Example:
        file_operations = [
            {'path': '/project/src/main.py', 'status': 'modified'},
            {'path': '/project/src/utils/helper.py', 'status': 'created'},
            {'path': '/project/tests/test_main.py', 'status': 'deleted'},
        ]
    """
    if not file_operations:
        return

    # Build directory tree structure
    tree_data: Dict[str, Dict] = {}

    for op in file_operations:
        path_str = op.get('path', '')
        status = op.get('status', 'unchanged')

        if not path_str:
            continue

        # Normalize path and split into parts
        path = Path(path_str)
        parts = list(path.parts)

        # Build nested structure
        current = tree_data
        for i, part in enumerate(parts):
            if part not in current:
                current[part] = {
                    '_children': {},
                    '_status': 'unchanged',
                    '_is_file': i == len(parts) - 1
                }

            # Update status if this is the target file
            if i == len(parts) - 1:
                current[part]['_status'] = status
                current[part]['_is_file'] = True

            current = current[part]['_children']

    # Determine status color mapping
    status_colors = {
        'modified': SUCCESS,    # Green
        'created': INFO,        # Cyan
        'deleted': ERROR,       # Red
        'unchanged': DIM,       # Gray
    }

    status_icons = {
        'modified': get_icon('✎'),
        'created': get_icon('◆'),
        'deleted': get_icon('✕'),
        'unchanged': get_icon('·'),
    }

    # Build rich Tree
    tree = Tree(f"[bold {TEXT}]{title}[/bold {TEXT}]", guide_style=BORDER)

    def add_tree_nodes(parent_node, data_dict, parent_path=""):
        """Recursively add nodes to the tree."""
        # Sort: directories first, then files; alphabetically within each group
        items = []
        for name, node_data in data_dict.items():
            is_file = node_data.get('_is_file', False)
            items.append((name, node_data, is_file))

        items.sort(key=lambda x: (x[2], x[0]))  # Sort by is_file, then name

        for name, node_data, is_file in items:
            status = node_data.get('_status', 'unchanged')
            children = node_data.get('_children', {})

            # Skip empty directories (no children and unchanged)
            if not is_file and not children and status == 'unchanged':
                continue

            color = status_colors.get(status, DIM)
            icon = status_icons.get(status, '·')

            # Create label
            if is_file:
                label = f"[{color}]{icon} {name}[/{color}]"
            else:
                label = f"[{ACCENT}]{get_icon('▸')} {name}/[/{ACCENT}]"

            # Add node
            if children:
                child_node = parent_node.add(label)
                add_tree_nodes(child_node, children, f"{parent_path}/{name}")
            else:
                parent_node.add(label)

    add_tree_nodes(tree, tree_data)

    console.print()
    console.print(tree)


def _detect_language_from_path(path: str) -> str:
    """Detect language from file extension."""
    ext_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.go': 'go',
        '.rs': 'rust',
        '.java': 'java',
        '.c': 'c',
        '.cpp': 'cpp',
        '.cc': 'cpp',
        '.cxx': 'cpp',
        '.h': 'c',
        '.hpp': 'cpp',
        '.sh': 'bash',
        '.bash': 'bash',
        '.zsh': 'bash',
        '.fish': 'fish',
        '.sql': 'sql',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.json': 'json',
        '.xml': 'xml',
        '.html': 'html',
        '.css': 'css',
        '.scss': 'scss',
        '.md': 'markdown',
        '.txt': 'text',
        '.toml': 'toml',
        '.ini': 'ini',
        '.cfg': 'ini',
        '.conf': 'ini',
        '.rb': 'ruby',
        '.php': 'php',
        '.swift': 'swift',
        '.kt': 'kotlin',
        '.dart': 'dart',
        '.r': 'r',
        '.m': 'matlab',
        '.jl': 'julia',
        '.vim': 'vim',
        '.lua': 'lua',
        '.pl': 'perl',
    }
    for ext, lang in ext_map.items():
        if path.endswith(ext):
            return lang
    return 'text'


def render_error(console: Console, message: str):
    panel = Panel(
        f"[{ERROR}]{message}[/{ERROR}]",
        title=f"[bold {ERROR}]Error[/bold {ERROR}]",
        title_align="left",
        border_style=ERROR,
        padding=(0, 2),
    )
    console.print()
    console.print(panel)


def render_assistant_message(console: Console, content: str):
    """Render assistant message as plain text (no markdown parsing)."""
    console.print()
    if not content.strip():
        return
    console.print(strip_markdown(content), markup=False, highlight=False)


def render_tool_call(console: Console, name, args, index=None, total=None):
    icons = {
        "read_file": get_icon("▸"), "create_file": get_icon("◆"), "write_file": get_icon("◆"),
        "str_replace": get_icon("✎"), "delete_file": get_icon("✕"), "list_directory": get_icon("≡"),
        "search_files": get_icon("⊙"), "bash": "$", "web_fetch": get_icon("◎"),
        "read_image": get_icon("▸"),
    }
    icon = icons.get(name, get_icon("·"))

    match name:
        case "bash":
            detail = args.get("command", "")
        case "read_file":
            detail = args.get("path", "")
            if "start_line" in args:
                detail += f" L{args.get('start_line','')}-{args.get('end_line','∞')}"
        case "create_file" | "write_file":
            n = args.get("content", "").count("\n") + 1
            detail = f"{args.get('path','')} ({n} lines)"
        case "str_replace":
            detail = args.get("path", "")
        case "list_directory":
            detail = args.get("path", ".")
        case "search_files":
            detail = f"/{args.get('pattern', '')}/ in {args.get('path', '.')}"
        case "web_fetch":
            detail = args.get("url", "")
        case _:
            detail = ""

    progress = ""
    if total and total > 1:
        progress = f"[{DIM}]{index}/{total}[/{DIM}] "

    console.print(f"\n  {progress}[{ACCENT}]{icon}[/{ACCENT}] [bold {TEXT}]{name}[/bold {TEXT}] [{DIM}]{detail}[/{DIM}]")

    # TUI mode: update activity bar with current tool
    if getattr(console, '_is_tui', False):
        try:
            console._app.set_activity_tool(name, detail)
        except Exception:
            pass


def render_result(console: Console, name, result, elapsed: float = 0,
                  web_display: str = "summary", format_preview_fn=None,
                  tool_arguments: dict = None, truncation_mode: str = "auto"):
    """Render tool result with syntax highlighting for code files."""
    from .formatters import format_result as format_tool_result

    if (
        name == "web_fetch"
        and web_display != "full"
        and not result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out"))
    ):
        if format_preview_fn is not None:
            result = format_preview_fn(result)

    time_str = f" [{SEPARATOR}]({elapsed:.1f}s)[/{SEPARATOR}]" if elapsed >= 0.1 else ""

    is_error = result.startswith(("⚠", "⛔", "⏱", "Error:", "Blocked:", "Timed out"))
    is_success = result.startswith(("Created", "Edited", "Overwrote", "Deleted", get_icon("✓"), "Found"))

    if is_error:
        lines = result.splitlines()
        preview = result if len(lines) <= 5 else "\n".join(lines[:5]) + f"\n     ... ({len(lines)-5} more)"
        console.print(f"     [{ERROR}]{preview}[/{ERROR}]{time_str}")
    elif is_success:
        first_line = result.split("\n", 1)[0]
        check_mark = get_icon("✓")
        if first_line.startswith(f"{check_mark} "):
            first_line = first_line[len(check_mark)+1:]
        elif first_line.startswith(check_mark):
            first_line = first_line[len(check_mark):].lstrip()
        console.print(f"     [{SUCCESS}]{check_mark} {first_line}[/{SUCCESS}]{time_str}")
    else:
        # Try formatters first (JSON, CSV, XML, large text)
        formatted = format_tool_result(
            content=result,
            tool_name=name,
            tool_arguments=tool_arguments or {},
            elapsed=elapsed
        )

        if formatted is not None:
            # Formatter handled it - render the formatted output
            console.print()
            console.print(formatted)
            if time_str:
                console.print(f"     {time_str}")
            return

        # Try to apply syntax highlighting for code files
        should_highlight = False
        lang = 'text'

        if name == "read_file" and tool_arguments:
            path = tool_arguments.get("path", "")
            if path:
                lang = _detect_language_from_path(path)
                should_highlight = lang != 'text'

        lines = result.splitlines()

        # Get adaptive truncation limit (40% of terminal height for tool results)
        truncate_limit = get_adaptive_truncate_limit(truncation_mode, percentage=0.4, min_lines=20)

        if should_highlight and len(lines) <= 1000:  # Limit for performance
            # Apply syntax highlighting
            try:
                display_lines = truncate_limit if truncate_limit > 0 else len(lines)
                syntax = Syntax(
                    result,
                    lang,
                    theme="monokai",
                    line_numbers=True,
                    word_wrap=False,
                    background_color="default",
                    line_range=(1, min(display_lines, len(lines)))
                )
                console.print()
                console.print(syntax)
                if truncate_limit > 0 and len(lines) > truncate_limit:
                    console.print(f"     [{DIM}]... ({len(lines)-truncate_limit} more lines)[/{DIM}]")
                if time_str:
                    console.print(f"     {time_str}")
                return
            except Exception:
                # Fall back to normal rendering if highlighting fails
                pass

        # Normal rendering (no syntax highlighting)
        if truncate_limit > 0 and len(lines) > truncate_limit:
            show_lines = lines[:truncate_limit - 5]
            show_lines.append(f"     ... ({len(lines) - (truncate_limit - 5)} more lines)")
        else:
            show_lines = lines
        output = "\n".join(f"     [{DIM}]{line}[/{DIM}]" for line in show_lines)
        if time_str:
            output += f"\n     {time_str}"
        console.print(output)


def render_write_diff(console: Console, tool_name: str, arguments: dict):
    if tool_name == "str_replace":
        old_str = arguments.get("old_str", "")
        new_str = arguments.get("new_str", "")
        parts = ["     [{border}]┌─[/{border}]".format(border=BORDER)]
        for line in old_str.splitlines()[:3]:
            parts.append(f"     [{BORDER}]│[/{BORDER}] [{ERROR}]- {line[:100]}[/{ERROR}]")
        for line in new_str.splitlines()[:3]:
            parts.append(f"     [{BORDER}]│[/{BORDER}] [{SUCCESS}]+ {line[:100]}[/{SUCCESS}]")
        old_lines = old_str.count('\n') + 1
        new_lines = new_str.count('\n') + 1
        if old_lines > 3 or new_lines > 3:
            parts.append(f"     [{BORDER}]│[/{BORDER}] [{DIM}]({old_lines} lines → {new_lines} lines)[/{DIM}]")
        parts.append(f"     [{BORDER}]└─[/{BORDER}]")
        console.print("\n".join(parts))
    elif tool_name in ("write_file", "create_file"):
        content = arguments.get("content", "")
        line_count = content.count('\n') + 1
        console.print(f"     [{DIM}]({line_count} lines written)[/{DIM}]")


def inject_error_hint(tool_name: str, arguments: dict, result: str, config=None) -> str:
    """Add intelligent, context-aware hints to error messages.

    Uses color-coded sections:
    - ERROR (red): The original error message
    - WARN (yellow): Contextual hints and explanations
    - INFO (blue): Suggestions and next steps
    """
    if not result.startswith(("Error:", "⚠", "⛔", "⏱", "Blocked:", "Timed out")):
        return result

    hint_parts = []

    # ── str_replace errors ──
    if tool_name == "str_replace":
        path = arguments.get("path", "")

        if "not found" in result.lower():
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] The exact search string was not found in the file."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTION:[/{INFO}] Use read_file on '{path}' to see the current content, "
                f"then retry str_replace with the exact text from the file."
            )

        elif "appears" in result.lower() and "x in" in result.lower():
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] The search string appears multiple times. "
                f"str_replace requires a unique match."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTION:[/{INFO}] Add more surrounding context to make the "
                f"search string unique, or use read_file to identify the exact location."
            )

        elif "not found" in result.lower() and path:
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] The file '{path}' does not exist."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTION:[/{INFO}] Use create_file to create it, or verify the path "
                f"with list_directory."
            )

    # ── create_file errors ──
    elif tool_name == "create_file":
        path = arguments.get("path", "")

        if "exists" in result.lower():
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] File already exists at '{path}'."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTIONS:[/{INFO}]\n"
                f"  • Use str_replace for targeted edits to preserve existing content\n"
                f"  • Use write_file to completely overwrite the file\n"
                f"  • Use read_file to inspect current content first"
            )

    # ── write_file errors ──
    elif tool_name == "write_file":
        path = arguments.get("path", "")

        if "not found" in result.lower() or "no such file" in result.lower():
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] Parent directory does not exist for '{path}'."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTION:[/{INFO}] The system will create parent directories "
                f"automatically. If this error persists, check for permission issues."
            )

        elif "permission denied" in result.lower():
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] Cannot write to '{path}' due to insufficient permissions."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTION:[/{INFO}] Check file permissions with 'bash ls -l {path}' "
                f"or try a different location."
            )

    # ── delete_file errors ──
    elif tool_name == "delete_file":
        path = arguments.get("path", "")

        if "not found" in result.lower():
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] File '{path}' does not exist."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTION:[/{INFO}] Use list_directory or find_files to locate "
                f"the correct path."
            )

        elif "directory" in result.lower():
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] '{path}' is a directory, not a file."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTION:[/{INFO}] Use bash 'rm -rf {path}' to delete directories "
                f"(use with caution!)."
            )

    # ── list_directory errors ──
    elif tool_name == "list_directory":
        path = arguments.get("path", ".")

        if "not found" in result.lower():
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] Directory '{path}' does not exist."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTION:[/{INFO}] Start with list_directory('.') to see the "
                f"project root, then navigate from there."
            )

        elif "not a directory" in result.lower():
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] '{path}' is a file, not a directory."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTION:[/{INFO}] Use read_file to view file contents, or "
                f"list_directory on the parent directory."
            )

    # ── search_files errors ──
    elif tool_name == "search_files":
        pattern = arguments.get("pattern", "")

        if "no matches" in result.lower():
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] Pattern '{pattern}' found no matches."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTIONS:[/{INFO}]\n"
                f"  • Try a broader search pattern\n"
                f"  • Check spelling and regex syntax\n"
                f"  • Use find_files to search by filename instead"
            )

        elif "invalid" in result.lower() and "regex" in result.lower():
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] Invalid regex pattern: '{pattern}'."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTION:[/{INFO}] Check regex syntax. Use simpler patterns or "
                f"escape special characters: . * + ? [ ] ( ) {{ }} ^ $ | \\"
            )

    # ── bash errors ──
    elif tool_name == "bash":
        command = arguments.get("command", "")

        if "blocked" in result.lower():
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] Command blocked by safety guards for security reasons."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTION:[/{INFO}] Avoid dangerous commands like 'rm -rf /', 'sudo', "
                f"'curl|sh'. Check blocked_commands in config."
            )

        elif "timed out" in result.lower():
            timeout_val = "30"  # default
            if config and hasattr(config, 'command_timeout'):
                timeout_val = str(config.command_timeout)

            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] Command exceeded timeout limit ({timeout_val}s)."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTIONS:[/{INFO}]\n"
                f"  • Command may be stuck or taking too long\n"
                f"  • Increase timeout in config: command-timeout\n"
                f"  • Run long commands in background or break into smaller steps\n"
                f"  • Check if command is waiting for input"
            )

        elif "command not found" in result.lower():
            cmd_name = command.split()[0] if command else ""
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] Command '{cmd_name}' is not installed or not in PATH."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTION:[/{INFO}] Install the required tool or verify the "
                f"command name. Use 'which {cmd_name}' to check availability."
            )

        elif "permission denied" in result.lower():
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] Insufficient permissions to execute the command."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTIONS:[/{INFO}]\n"
                f"  • Check file/directory permissions\n"
                f"  • Ensure executable has correct permissions (chmod +x)\n"
                f"  • Verify you have access to the target resource"
            )

        else:
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] Command failed with an error."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTION:[/{INFO}] Review the error output above. Check for:\n"
                f"  • Typos in command or arguments\n"
                f"  • Missing dependencies or tools\n"
                f"  • Incorrect file paths\n"
                f"  • Syntax errors in shell command"
            )

    # ── Generic fallback for other tools ──
    else:
        if "not found" in result.lower():
            hint_parts.append(
                f"[{WARN}]HINT:[/{WARN}] Resource not found."
            )
            hint_parts.append(
                f"[{INFO}]SUGGESTION:[/{INFO}] Verify paths and spelling. Use exploration tools "
                f"like list_directory, find_files, or search_files."
            )

    # Combine original error with hints
    if hint_parts:
        return result + "\n\n" + "\n".join(hint_parts)

    return result

def build_diff_panel(diff: str, max_lines: int = 50, truncation_mode: str = "auto") -> Panel:
    """Build a rich diff panel with stats, hunk headers, and character-level highlighting.

    Features:
    - Diff statistics header (+N -M | X files changed)
    - Complete hunk headers (@@ -10,5 +10,8 @@)
    - Character-level highlighting for modified lines
    - Truncation indicator for large diffs (>max_lines)
    - Color scheme: red (removed), green (added), yellow (modified parts)

    Args:
        diff: The diff string to render
        max_lines: Maximum lines to show (only used if truncation_mode is "fixed")
        truncation_mode: "auto" (adaptive based on terminal), "fixed" (use max_lines), or "none"
    """
    from .diff_utils import compute_diff_stats, get_char_level_diff

    # Calculate adaptive max_lines if in auto mode (60% of terminal height for diffs)
    if truncation_mode == "auto":
        max_lines = get_adaptive_truncate_limit(truncation_mode, percentage=0.6, min_lines=20)
    elif truncation_mode == "none":
        max_lines = -1  # No limit

    diff_text = Text()
    all_lines = diff.splitlines()

    # Compute and display diff statistics
    added, removed, files_changed = compute_diff_stats(diff)
    if added > 0 or removed > 0:
        stats_parts = []
        if added > 0:
            stats_parts.append(f"+{added}")
        if removed > 0:
            stats_parts.append(f"-{removed}")
        stats = " ".join(stats_parts)

        file_text = f"{files_changed} file{'s' if files_changed != 1 else ''} changed"
        diff_text.append(f"{stats} | {file_text}\n", style=f"bold {INFO}")
        diff_text.append("\n")

    # Track consecutive add/remove pairs for character-level diff
    pending_remove = []
    pending_add = []

    def flush_pending():
        """Flush pending add/remove pairs with character-level diff."""
        nonlocal pending_remove, pending_add

        if not pending_remove and not pending_add:
            return

        # If we have exactly one remove and one add, do character-level diff
        if len(pending_remove) == 1 and len(pending_add) == 1:
            old_line = pending_remove[0][1:]  # Strip '-' prefix
            new_line = pending_add[0][1:]     # Strip '+' prefix

            # Only do char-level diff if lines are similar enough
            if _lines_similar(old_line, new_line):
                # Render old line with char-level highlighting
                diff_text.append("-", style=ERROR)
                old_parts, new_parts = get_char_level_diff(old_line, new_line)
                for text, is_changed in old_parts:
                    if is_changed:
                        diff_text.append(text, style=f"bold {ERROR} on rgb(90,0,0)")
                    else:
                        diff_text.append(text, style=ERROR)
                diff_text.append("\n")

                # Render new line with char-level highlighting
                diff_text.append("+", style=SUCCESS)
                for text, is_changed in new_parts:
                    if is_changed:
                        diff_text.append(text, style=f"bold {SUCCESS} on rgb(0,60,0)")
                    else:
                        diff_text.append(text, style=SUCCESS)
                diff_text.append("\n")

                pending_remove.clear()
                pending_add.clear()
                return

        # Otherwise, render normally without char-level diff
        for line in pending_remove:
            diff_text.append(line, style=ERROR)
            diff_text.append("\n")
        for line in pending_add:
            diff_text.append(line, style=SUCCESS)
            diff_text.append("\n")

        pending_remove.clear()
        pending_add.clear()

    # Process diff lines
    shown_lines = 0
    truncated = False

    for line in all_lines:
        # Check if we've exceeded max_lines (skip check if max_lines < 0, which means no truncation)
        if max_lines > 0 and shown_lines >= max_lines:
            truncated = True
            break

        # File headers (--- +++)
        if line.startswith('---') or line.startswith('+++'):
            flush_pending()
            diff_text.append(line, style=DIM)
            diff_text.append("\n")
            shown_lines += 1

        # Hunk headers (@@)
        elif line.startswith('@@'):
            flush_pending()
            # Display complete hunk header with line numbers
            diff_text.append(line, style=f"bold {INFO}")
            diff_text.append("\n")
            shown_lines += 1

        # Removed lines
        elif line.startswith('-') and not line.startswith('---'):
            pending_remove.append(line)
            shown_lines += 1

        # Added lines
        elif line.startswith('+') and not line.startswith('+++'):
            pending_add.append(line)
            shown_lines += 1

        # Context lines
        else:
            flush_pending()
            diff_text.append(line, style=DIM)
            diff_text.append("\n")
            shown_lines += 1

    # Flush any remaining pending lines
    flush_pending()

    # Add truncation indicator
    if truncated:
        remaining = len(all_lines) - shown_lines
        diff_text.append(f"\n[Diff truncated: {remaining} more lines omitted]", style=f"italic {WARN}")

    return Panel(diff_text, border_style=BORDER, padding=(0, 1), expand=False)


def _lines_similar(line1: str, line2: str, threshold: float = 0.4) -> bool:
    """Check if two lines are similar enough to warrant character-level diff.

    Uses ratio of common characters to determine similarity.
    """
    import difflib
    ratio = difflib.SequenceMatcher(None, line1, line2).ratio()
    return ratio >= threshold


def show_edit_preview(console: Console, tool_name: str, arguments: dict, files_tools, truncation_mode: str = "auto"):
    path = arguments.get("path", "")
    old_str = arguments.get("old_str", "")
    new_str = arguments.get("new_str", "")
    can_apply, diff = files_tools.preview_str_replace(path, old_str, new_str)
    if can_apply and diff:
        console.print(build_diff_panel(diff, truncation_mode=truncation_mode))
    elif not can_apply:
        console.print(f"  [{WARN}]⚠ {diff}[/{WARN}]")


def show_write_preview(console: Console, arguments: dict, files_tools, truncation_mode: str = "auto"):
    path = arguments.get("path", "")
    content = arguments.get("content", "")
    is_overwrite, diff = files_tools.preview_write_file(path, content)
    if is_overwrite and diff:
        console.print(build_diff_panel(diff, truncation_mode=truncation_mode))
    else:
        console.print(f"  [{DIM}]{diff}[/{DIM}]")


def confirm_tool(console: Console, tool_name: str, arguments: dict, files_tools) -> str:
    """Show preview and prompt user. Returns 'yes', 'always', or 'no'."""
    try:
        # Store tool info for TUI ConfirmPanel (if running in TUI mode)
        if getattr(console, '_is_tui', False):
            console._pending_confirm_tool = tool_name
            console._pending_confirm_detail = _confirm_detail(tool_name, arguments)

        if tool_name == "str_replace":
            show_edit_preview(console, tool_name, arguments, files_tools)
        elif tool_name == "write_file":
            show_write_preview(console, arguments, files_tools)
        elif tool_name == "bash":
            cmd = arguments.get("command", "")
            console.print(f"  [{DIM}]$[/{DIM}] {cmd}")

        ans = console.input(
            f"  [{WARN}]?[/{WARN}] "
            f"[bold {TEXT}](y)[/bold {TEXT}][{MUTED}]es[/{MUTED}] / "
            f"[bold {TEXT}](n)[/bold {TEXT}][{MUTED}]o[/{MUTED}] / "
            f"[bold {TEXT}](a)[/bold {TEXT}][{MUTED}]lways[/{MUTED}]: "
        ).strip().lower()
        if ans in ("a", "always"):
            return "always"
        if ans in ("y", "yes", ""):
            return "yes"
        return "no"
    except (KeyboardInterrupt, EOFError):
        return "no"


def _confirm_detail(tool_name: str, arguments: dict) -> str:
    """Extract a short detail string for the TUI confirm panel."""
    if tool_name == "bash":
        cmd = arguments.get("command", "")
        return cmd[:80] if cmd else ""
    elif tool_name == "str_replace":
        return arguments.get("path", "")
    elif tool_name in ("write_file", "create_file"):
        path = arguments.get("path", "")
        n = arguments.get("content", "").count("\n") + 1
        return f"{path} ({n} lines)" if path else ""
    elif tool_name == "delete_file":
        return arguments.get("path", "")
    return ""


def handle_image_result(conversation: list, tc, files_tools):
    """Handle image tool result for multimodal LLM."""
    path = tc.arguments.get("path", "")
    try:
        img_data = files_tools.read_image(path)
        content = [
            {"type": "text", "text": f"Image loaded: {path} ({img_data['size']} bytes)"},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{img_data['media_type']};base64,{img_data['data']}"
                }
            }
        ]
        conversation.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": content
        })
    except Exception as e:
        conversation.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": f"Error loading image: {e}"
        })


def render_parallel_tools(console: Console, tool_calls: list, status_dict: dict) -> Live:
    """Render real-time parallel tool execution visualization.

    Args:
        console: Rich console for rendering
        tool_calls: List of tool call objects with .name attribute
        status_dict: Shared dict tracking tool status {"tool_id": {"status": str, "elapsed": float, "name": str}}

    Returns:
        Live context manager for real-time updates

    Usage:
        status_dict = {}
        with render_parallel_tools(console, tool_calls, status_dict) as live:
            # Update status_dict during execution
            status_dict[tool_id] = {"status": "running", "elapsed": 0.5, "name": "read_file"}
    """
    def generate_table() -> Table:
        """Generate the current state table."""
        table = Table(
            title=f"[bold {ACCENT}]Parallel Tool Execution[/bold {ACCENT}]",
            show_header=True,
            header_style=f"bold {INFO}",
            border_style=BORDER,
            padding=(0, 1),
        )

        table.add_column("Tool", style=TEXT, no_wrap=True)
        table.add_column("Status", style=TEXT, no_wrap=True)
        table.add_column("Time", style=DIM, justify="right", no_wrap=True)

        # Count completed tools
        completed = sum(1 for s in status_dict.values() if s.get("status") == "completed")
        total = len(tool_calls)

        # Add rows for each tool
        for tc in tool_calls:
            tool_info = status_dict.get(tc.id, {})
            tool_name = tool_info.get("name", tc.name)
            status = tool_info.get("status", "queued")
            elapsed = tool_info.get("elapsed", 0.0)

            # Status icon and color
            if status == "queued":
                status_text = f"[{DIM}]{get_icon('⋯')} queued[/{DIM}]"
                time_text = f"[{DIM}]-[/{DIM}]"
            elif status == "running":
                status_text = f"[{INFO}]{get_icon('▸')} running[/{INFO}]"
                time_text = f"[{DIM}]{elapsed:.1f}s[/{DIM}]"
            elif status == "completed":
                # Color based on speed: green (<100ms), yellow (100ms-1s), default (>1s)
                if elapsed < 0.1:
                    time_style = SUCCESS
                elif elapsed > 1.0:
                    time_style = WARN
                else:
                    time_style = DIM
                status_text = f"[{SUCCESS}]{get_icon('✓')} completed[/{SUCCESS}]"
                time_text = f"[{time_style}]{elapsed:.1f}s[/{time_style}]"
            else:  # error
                status_text = f"[{ERROR}]{get_icon('✕')} error[/{ERROR}]"
                time_text = f"[{DIM}]{elapsed:.1f}s[/{DIM}]"

            table.add_row(tool_name, status_text, time_text)

        # Add progress summary
        percentage = int((completed / total) * 100) if total > 0 else 0
        if completed < total:
            progress_text = f"[{INFO}]{completed}/{total} tools completed ({percentage}%)[/{INFO}]"
        else:
            progress_text = f"[{SUCCESS}]All {total} tools completed[/{SUCCESS}]"

        table.caption = progress_text

        return table

    # Create and return Live context
    live = Live(generate_table(), console=console, refresh_per_second=4, transient=False)
    live.generate_table = generate_table  # Attach for external updates
    return live
