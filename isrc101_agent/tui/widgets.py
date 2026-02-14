"""Custom Textual widgets for the isrc101-agent TUI."""

from __future__ import annotations

from typing import Sequence

from textual.reactive import reactive
from textual.widgets import Input, Static
from textual.message import Message
from rich.text import Text


class StatusBar(Static):
    """Status bar showing model, mode, and context usage.

    Compact single-line bar at the bottom of the screen.
    """

    model_name = reactive("")
    mode = reactive("agent")
    ctx_pct = reactive(0)
    ctx_remaining = reactive(0)
    total_tokens = reactive(0)

    def render(self) -> Text:
        parts = Text()
        parts.append(" model:", style="#6E7681")
        parts.append(f"{self.model_name} ", style="#7FA6D9 bold")
        parts.append(" mode:", style="#6E7681")
        parts.append(f"{self.mode} ", style="#C8D8EE")
        parts.append(" ctx:", style="#6E7681")

        if self.ctx_pct >= 90:
            pct_style = "#F85149 bold"
        elif self.ctx_pct >= 70:
            pct_style = "#E3B341"
        else:
            pct_style = "#57DB9C"
        parts.append(f"{self.ctx_pct}% ", style=pct_style)

        if self.ctx_remaining > 0:
            remaining = self._fmt_tokens(self.ctx_remaining)
            parts.append(f"({remaining} left) ", style="#C8D8EE")

        if self.total_tokens > 0:
            tok_str = self._fmt_tokens(self.total_tokens)
            parts.append(f" tok:{tok_str} ", style="#C8D8EE")

        return parts

    @staticmethod
    def _fmt_tokens(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 10_000:
            return f"{n / 1_000:.0f}k"
        if n >= 1_000:
            return f"{n / 1_000:.1f}k"
        return str(n)


# ---------------------------------------------------------------------------
# ActivityBar — live tool activity indicator (like Claude Code's "● Read 1 file")
# ---------------------------------------------------------------------------

class ActivityBar(Static):
    """Single-line activity indicator shown above the input during tool use.

    Displays the current operation in Claude-Code style:
        ● Read  src/main.py
        ● Bash  npm test
        ● Thinking...

    Hidden when idle.  Updated from worker threads via
    ``app.set_activity()`` / ``app.clear_activity()``.
    """

    TOOL_ICONS = {
        "read_file": "Read", "create_file": "Write", "write_file": "Write",
        "str_replace": "Edit", "delete_file": "Delete", "list_directory": "List",
        "search_files": "Search", "bash": "Bash", "web_fetch": "Fetch",
        "web_search": "Search", "read_image": "Read",
    }

    activity_text = reactive("")

    def render(self) -> Text:
        if not self.activity_text:
            return Text("")
        t = Text()
        t.append(" \u25cf ", style="bold #57DB9C")
        t.append(self.activity_text, style="#8B949E")
        return t

    def watch_activity_text(self, value: str) -> None:
        self.display = bool(value)

    def set_tool(self, tool_name: str, detail: str = "") -> None:
        """Set activity from a tool call name + detail."""
        label = self.TOOL_ICONS.get(tool_name, tool_name)
        if detail:
            # Truncate long details
            if len(detail) > 60:
                detail = detail[:57] + "..."
            self.activity_text = f"{label}  {detail}"
        else:
            self.activity_text = label

    def set_thinking(self, brief: str = "") -> None:
        """Set activity to thinking/reasoning state."""
        if brief:
            if len(brief) > 60:
                brief = brief[:57] + "..."
            self.activity_text = f"Thinking  {brief}"
        else:
            self.activity_text = "Thinking..."

    def set_progress(self, message: str, elapsed: float = 0) -> None:
        """Set activity to a progress message (e.g. running command)."""
        if elapsed > 0:
            self.activity_text = f"{message}  ({elapsed:.1f}s)"
        else:
            self.activity_text = message

    def clear(self) -> None:
        self.activity_text = ""


# ---------------------------------------------------------------------------
# SelectionInput — Textual-native interactive picker (replaces prompt_toolkit)
# ---------------------------------------------------------------------------

class SelectionInput(Static):
    """Arrow-key navigable selection list.

    Temporarily mounted in place of ``ChatInput`` (same pattern as
    ``ConfirmInput``).  Posts ``Selected`` on Enter and ``Cancelled`` on
    Escape, then the app removes it.
    """

    class Selected(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    class Cancelled(Message):
        pass

    can_focus = True

    def __init__(
        self,
        title: str,
        options: list[tuple[str, str]],
        active: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._title = title
        self._options = options        # [(display_label, value), ...]
        self._active = active
        self._cursor = 0
        # Set initial cursor to active item
        for i, (_, v) in enumerate(options):
            if v == active:
                self._cursor = i
                break

    def render(self) -> Text:
        text = Text()
        text.append(f" {self._title}\n", style="bold #7FA6D9")
        text.append(" \u2191\u2193 move \u00b7 Enter select \u00b7 Esc cancel\n\n", style="#6E7681")
        for i, (label, value) in enumerate(self._options):
            pointer = "\u203a" if i == self._cursor else " "
            is_active = value == self._active
            marker = "\u25cf" if is_active else " "
            if i == self._cursor:
                style = "bold #E7EEF8"
            elif is_active:
                style = "#57DB9C"
            else:
                style = "#C8D8EE"
            text.append(f" {pointer} {marker} {label}\n", style=style)
        return text

    def on_key(self, event) -> None:
        if event.key in ("up", "k"):
            event.prevent_default()
            event.stop()
            self._cursor = max(0, self._cursor - 1)
            self.refresh()
        elif event.key in ("down", "j"):
            event.prevent_default()
            event.stop()
            self._cursor = min(len(self._options) - 1, self._cursor + 1)
            self.refresh()
        elif event.key == "enter":
            event.prevent_default()
            event.stop()
            if self._options:
                self.post_message(self.Selected(self._options[self._cursor][1]))
        elif event.key == "escape":
            event.prevent_default()
            event.stop()
            self.post_message(self.Cancelled())


# ---------------------------------------------------------------------------
# CommandPalette — slash command autocomplete overlay
# ---------------------------------------------------------------------------

class CommandPalette(Static):
    """Floating slash-command palette shown above the input.

    Hidden by default.  ``update_filter(text)`` is called every time the
    ``ChatInput`` value changes.  When the text starts with ``/``, the
    palette shows matching commands and allows arrow-key navigation.
    """

    DEFAULT_CSS = """
    CommandPalette {
        dock: bottom;
        height: auto;
        max-height: 14;
        background: #161B22;
        color: #E6EDF3;
        padding: 0 1;
        display: none;
    }
    """

    def __init__(self, specs: Sequence = (), **kwargs):
        super().__init__(**kwargs)
        self._specs = list(specs)
        self._visible_specs: list = []
        self._cursor = 0

    def update_filter(self, text: str) -> None:
        """Recompute visible commands from current input text."""
        if not text.startswith("/") or " " in text.strip():
            self._visible_specs = []
            self._cursor = 0
            self.display = False
            return

        query = text.lower()
        query_body = query.lstrip("/")
        matched = []
        for spec in self._specs:
            cmd_body = spec.command.lstrip("/")
            if not query_body:
                matched.append(spec)
            elif cmd_body.startswith(query_body):
                matched.append(spec)
            elif query_body in cmd_body or query_body in spec.description.lower():
                matched.append(spec)
            elif any(query_body in kw for kw in spec.keywords):
                matched.append(spec)

        self._visible_specs = matched[:16]
        self._cursor = min(self._cursor, max(0, len(self._visible_specs) - 1))
        self.display = bool(self._visible_specs)
        self.refresh()

    def render(self) -> Text:
        text = Text()
        for i, spec in enumerate(self._visible_specs):
            pointer = "\u203a " if i == self._cursor else "  "
            if i == self._cursor:
                style = "bold #E7EEF8"
            else:
                style = "#8B949E"
            text.append(f"{pointer}{spec.command:<16} {spec.description}\n", style=style)
        return text

    def move_up(self) -> None:
        if self._visible_specs:
            self._cursor = max(0, self._cursor - 1)
            self.refresh()

    def move_down(self) -> None:
        if self._visible_specs:
            self._cursor = min(len(self._visible_specs) - 1, self._cursor + 1)
            self.refresh()

    def get_selected_command(self) -> str:
        """Return the currently highlighted command string, or ''."""
        if self._visible_specs and 0 <= self._cursor < len(self._visible_specs):
            return self._visible_specs[self._cursor].command
        return ""

    @property
    def is_active(self) -> bool:
        return self.display and bool(self._visible_specs)


class ChatInput(Input):
    """Chat input with history navigation and command prefix handling.

    Enter submits, Escape refocuses, Up/Down navigate history.
    When text starts with '/' and a ``CommandPalette`` is present, arrow
    keys navigate the palette instead of history.
    """

    class Submitted(Message):
        """Posted when user submits input (Enter key)."""
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(self, **kwargs):
        super().__init__(
            placeholder="Type a message... (/ for commands)",
            **kwargs,
        )
        self._history: list[str] = []
        self._history_idx = -1
        self._draft = ""

    def _get_palette(self) -> CommandPalette | None:
        """Find the CommandPalette sibling, if mounted."""
        try:
            return self.app.query_one("#command_palette", CommandPalette)
        except Exception:
            return None

    def on_key(self, event) -> None:
        palette = self._get_palette()

        # When palette is showing, arrow keys navigate it
        if palette and palette.is_active:
            if event.key == "up":
                event.prevent_default()
                event.stop()
                palette.move_up()
                return
            elif event.key == "down":
                event.prevent_default()
                event.stop()
                palette.move_down()
                return
            elif event.key == "tab":
                # Tab accepts the palette selection into the input
                event.prevent_default()
                event.stop()
                cmd = palette.get_selected_command()
                if cmd:
                    self.value = cmd + " "
                    self.cursor_position = len(self.value)
                return

        # Normal history navigation
        if event.key == "up" and self._history:
            event.prevent_default()
            event.stop()
            if self._history_idx == -1:
                self._draft = self.value
            self._history_idx = min(self._history_idx + 1, len(self._history) - 1)
            self.value = self._history[self._history_idx]
            self.cursor_position = len(self.value)
        elif event.key == "down":
            event.prevent_default()
            event.stop()
            if self._history_idx > 0:
                self._history_idx -= 1
                self.value = self._history[self._history_idx]
            elif self._history_idx == 0:
                self._history_idx = -1
                self.value = self._draft
            self.cursor_position = len(self.value)

    def watch_value(self, value: str) -> None:
        """Called whenever the input value changes — updates palette filter."""
        palette = self._get_palette()
        if palette:
            palette.update_filter(value)

    def action_submit(self) -> None:
        """Override default submit to add history tracking."""
        palette = self._get_palette()
        # If palette is active and user presses Enter, accept the command
        if palette and palette.is_active:
            cmd = palette.get_selected_command()
            if cmd:
                # If input is just a prefix like "/m", replace with full command and submit
                if self.value.strip() != cmd:
                    self.value = cmd
                # Hide palette before submitting
                palette.update_filter("")

        value = self.value.strip()
        if value:
            self._history.insert(0, value)
            if len(self._history) > 200:
                self._history = self._history[:200]
        self._history_idx = -1
        self._draft = ""
        self.post_message(self.Submitted(value))
        self.value = ""


class ConfirmPanel(Static):
    """Floating confirmation panel for tool permissions.

    Similar to Claude Code's permission popup:
    - Shows tool name + key detail
    - Single keypress: y = accept, n = reject, a = always, Esc = cancel
    - No Enter required — instant response
    - Visually distinct with warning-colored border

    Always present in compose() (hidden by default) to avoid
    dynamic mount/unmount lifecycle bugs.
    """

    class Answered(Message):
        def __init__(self, answer: str) -> None:
            super().__init__()
            self.answer = answer

    can_focus = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tool_name = ""
        self._detail = ""

    def show_confirm(self, tool_name: str, detail: str = "") -> None:
        """Populate and show the confirmation panel."""
        self._tool_name = tool_name
        self._detail = detail
        self.display = True
        self.refresh()
        self.focus()

    def hide(self) -> None:
        self.display = False

    def render(self) -> Text:
        t = Text()
        t.append("  \u26a1 ", style="bold #E3B341")
        t.append("Allow ", style="bold #E6EDF3")
        t.append(self._tool_name, style="bold #7FA6D9")
        if self._detail:
            detail = self._detail
            if len(detail) > 70:
                detail = detail[:67] + "..."
            t.append(f"  {detail}", style="#8B949E")
        t.append("  ?", style="bold #E3B341")
        t.append("\n")
        t.append("  ", style="")
        t.append(" y ", style="bold #0D1117 on #57DB9C")
        t.append(" Accept  ", style="#57DB9C")
        t.append(" n ", style="bold #0D1117 on #F85149")
        t.append(" Reject  ", style="#F85149")
        t.append(" a ", style="bold #0D1117 on #7FA6D9")
        t.append(" Always  ", style="#7FA6D9")
        t.append(" esc ", style="bold #6E7681")
        t.append("Cancel", style="#6E7681")
        return t

    def on_key(self, event) -> None:
        if event.key in ("y", "Y", "enter"):
            event.prevent_default()
            event.stop()
            self.display = False
            self.post_message(self.Answered("y"))
        elif event.key in ("n", "N"):
            event.prevent_default()
            event.stop()
            self.display = False
            self.post_message(self.Answered("n"))
        elif event.key in ("a", "A"):
            event.prevent_default()
            event.stop()
            self.display = False
            self.post_message(self.Answered("a"))
        elif event.key == "escape":
            event.prevent_default()
            event.stop()
            self.display = False
            self.post_message(self.Answered("n"))
