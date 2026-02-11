"""Terminal rendering and user confirmation logic."""

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

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
]


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
    width = console.width or 120
    separator = "─" * width
    console.print()
    console.print(f"[{SEPARATOR}]{separator}[/{SEPARATOR}]")
    if content.strip():
        console.print(Markdown(content))
    else:
        console.print(content)
    console.print(f"[{SEPARATOR}]{separator}[/{SEPARATOR}]")


def render_tool_call(console: Console, name, args, index=None, total=None):
    icons = {
        "read_file": "▸", "create_file": "◆", "write_file": "◆",
        "str_replace": "✎", "delete_file": "✕", "list_directory": "≡",
        "search_files": "⊙", "bash": "$", "web_fetch": "◎",
        "read_image": "▣",
    }
    icon = icons.get(name, "·")

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


def render_result(console: Console, name, result, elapsed: float = 0,
                  web_display: str = "summary", format_preview_fn=None):
    if (
        name == "web_fetch"
        and web_display != "full"
        and not result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out"))
    ):
        if format_preview_fn is not None:
            result = format_preview_fn(result)

    time_str = f" [{SEPARATOR}]({elapsed:.1f}s)[/{SEPARATOR}]" if elapsed >= 0.1 else ""

    is_error = result.startswith(("⚠", "⛔", "⏱", "Error:", "Blocked:", "Timed out"))
    is_success = result.startswith(("Created", "Edited", "Overwrote", "Deleted", "✓", "Found"))

    if is_error:
        lines = result.splitlines()
        preview = result if len(lines) <= 5 else "\n".join(lines[:5]) + f"\n     ... ({len(lines)-5} more)"
        console.print(f"     [{ERROR}]{preview}[/{ERROR}]{time_str}")
    elif is_success:
        first_line = result.split("\n", 1)[0]
        if first_line.startswith("✓ "):
            first_line = first_line[2:]
        elif first_line.startswith("✓"):
            first_line = first_line[1:].lstrip()
        console.print(f"     [{SUCCESS}]✓ {first_line}[/{SUCCESS}]{time_str}")
    else:
        lines = result.splitlines()
        if len(lines) > 20:
            show_lines = lines[:15]
            show_lines.append(f"     ... ({len(lines)-15} more lines)")
        else:
            show_lines = lines[:20]
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


def inject_error_hint(tool_name: str, arguments: dict, result: str) -> str:
    if not result.startswith(("Error:", "⚠")):
        return result

    if tool_name == "str_replace" and "not found" in result.lower():
        path = arguments.get("path", "")
        return (result + "\n\nHINT: The exact search string was not found in the file. "
                f"Use read_file on '{path}' to see the current content, "
                "then retry str_replace with the exact text from the file.")

    if tool_name == "bash":
        return (result + "\n\nHINT: The command failed. Review the error output above, "
                "check for typos or missing dependencies, and adjust the command.")

    if tool_name == "create_file" and "exists" in result.lower():
        return (result + "\n\nHINT: File already exists. Use str_replace for targeted edits "
                "or write_file to overwrite the entire file.")

    return result


def build_diff_panel(diff: str) -> Panel:
    diff_text = Text()
    all_lines = diff.splitlines()
    for i, line in enumerate(all_lines[:30]):
        if i > 0:
            diff_text.append("\n")
        if line.startswith('+') and not line.startswith('+++'):
            diff_text.append(line, style=SUCCESS)
        elif line.startswith('-') and not line.startswith('---'):
            diff_text.append(line, style=ERROR)
        elif line.startswith('@@'):
            diff_text.append(line, style=INFO)
        else:
            diff_text.append(line, style=DIM)
    if len(all_lines) > 30:
        diff_text.append(f"\n… {len(all_lines) - 30} more lines", style=DIM)
    return Panel(diff_text, border_style=BORDER, padding=(0, 1), expand=False)


def show_edit_preview(console: Console, tool_name: str, arguments: dict, files_tools):
    path = arguments.get("path", "")
    old_str = arguments.get("old_str", "")
    new_str = arguments.get("new_str", "")
    can_apply, diff = files_tools.preview_str_replace(path, old_str, new_str)
    if can_apply and diff:
        console.print(build_diff_panel(diff))
    elif not can_apply:
        console.print(f"  [{WARN}]⚠ {diff}[/{WARN}]")


def show_write_preview(console: Console, arguments: dict, files_tools):
    path = arguments.get("path", "")
    content = arguments.get("content", "")
    is_overwrite, diff = files_tools.preview_write_file(path, content)
    if is_overwrite and diff:
        console.print(build_diff_panel(diff))
    else:
        console.print(f"  [{DIM}]{diff}[/{DIM}]")


def confirm_tool(console: Console, tool_name: str, arguments: dict, files_tools) -> str:
    """Show preview and prompt user. Returns 'yes', 'always', or 'no'."""
    try:
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
