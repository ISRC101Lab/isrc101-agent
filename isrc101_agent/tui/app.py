"""ISRCApp — Textual fullscreen TUI for isrc101-agent."""

from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

from textual.app import App, ComposeResult
from textual.widgets import RichLog
from textual.worker import Worker, WorkerState
from rich.text import Text

from .console_adapter import TUIConsole
from .widgets import ActivityBar, ChatInput, CommandPalette, ConfirmPanel, SelectionInput, StatusBar


class ISRCApp(App):
    """Fullscreen TUI for isrc101-agent.

    Layout (no Header — mouse capture disabled for native text selection):
        RichLog         — scrollable message area
        ActivityBar     — live tool activity indicator (hidden when idle)
        CommandPalette  — slash-command autocomplete (hidden by default)
        StatusBar       — model/mode/ctx%
        ChatInput       — minimal input with top separator
    """

    CSS_PATH = "app.tcss"
    TITLE = "isrc101-agent"

    # Disable Textual's built-in command palette (we have our own CommandPalette widget)
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        ("ctrl+c", "interrupt", "Interrupt"),
        ("ctrl+d", "quit_app", "Quit"),
        ("escape", "focus_input", "Focus input"),
    ]

    def __init__(
        self,
        agent: Any,
        config: Any,
        llm: Any,
        tools: Any,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.agent = agent
        self.config = config
        self.llm = llm
        self.tools = tools
        self._tui_console: Optional[TUIConsole] = None
        self._current_worker: Optional[Worker] = None
        self._pending_ctrl_d = False
        # Confirm state (floating panel, no dynamic mount/unmount)
        self._confirm_event: Optional[threading.Event] = None
        self._confirm_result: Optional[list[str]] = None
        # Selection callback state
        self._selection_callback: Optional[Callable[[str], None]] = None

    def compose(self) -> ComposeResult:
        from ..ui import SLASH_COMMAND_SPECS

        # No Header — keeps UI minimal and avoids mouse capture
        yield RichLog(id="messages", highlight=True, markup=True, wrap=True)
        yield ActivityBar(id="activity")
        yield ConfirmPanel(id="confirm_panel")
        yield CommandPalette(specs=SLASH_COMMAND_SPECS, id="command_palette")
        yield StatusBar(id="statusbar")
        yield ChatInput(id="input")

    def on_mount(self) -> None:
        """Initialize TUI console adapter and render startup info."""
        self._tui_console = TUIConsole(self)

        # Disable mouse tracking so terminal-native text selection works.
        # Textual enables mouse reporting by default; we send ANSI escape
        # sequences to turn it off.  All interaction is keyboard-driven.
        import sys
        sys.stdout.write(
            "\x1b[?1000l"   # disable normal tracking
            "\x1b[?1002l"   # disable button-event tracking
            "\x1b[?1003l"   # disable any-event tracking
            "\x1b[?1006l"   # disable SGR extended mode
        )
        sys.stdout.flush()

        # Inject TUI console into agent module
        from .. import agent as agent_mod

        agent_mod.console = self._tui_console

        # Render startup banner
        from ..ui import render_startup

        render_startup(self._tui_console, self.config)

        if hasattr(self.config, "_missing_skills_msg") and self.config._missing_skills_msg:
            self._tui_console.print(self.config._missing_skills_msg)

        # Initial status bar update
        self._update_status()

        # Focus input
        self.query_one("#input", ChatInput).focus()

    # ── Input handling ─────────────────────────────────────

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle user input submission."""
        user_input = event.value.strip()
        if not user_input:
            return

        self._pending_ctrl_d = False

        # Display user message in log
        log = self.query_one("#messages", RichLog)
        user_text = Text()
        user_text.append("> ", style="bold #7FA6D9")
        user_text.append(user_input, style="bold #E6EDF3")
        log.write(user_text)
        log.write(Text(""))  # blank line

        if user_input.startswith("/"):
            self._handle_command(user_input)
            return

        # Run agent chat in background thread
        self._run_chat(user_input)

    def _handle_command(self, user_input: str) -> None:
        """Route slash commands."""
        from ..command_router import handle_command

        result = handle_command(
            user_input,
            console=self._tui_console,
            agent=self.agent,
            config=self.config,
            llm=self.llm,
            tools=self.tools,
        )
        if result == "quit":
            self._do_quit()
            return
        self._update_status()

    def _run_chat(self, user_input: str) -> None:
        """Launch agent.chat() in a background thread."""
        inp = self.query_one("#input", ChatInput)
        inp.disabled = True
        # Show thinking activity
        activity = self.query_one("#activity", ActivityBar)
        activity.set_thinking()

        self._current_worker = self.run_worker(
            lambda: self._chat_worker(user_input),
            thread=True,
            name="agent_chat",
        )

    def _chat_worker(self, user_input: str) -> None:
        """Runs in background thread — calls agent.chat()."""
        try:
            self.agent.chat(user_input)
        except KeyboardInterrupt:
            self._tui_console.print("[#E3B341]  Interrupted.[/#E3B341]")
        except Exception as error:
            self._tui_console.print(f"[#F85149]  Error: {error}[/#F85149]")
            if self.config.verbose:
                self._tui_console.print(
                    f"[#6E7681]{traceback.format_exc()}[/#6E7681]"
                )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Called when a worker changes state (started, success, error, etc)."""
        if event.worker.name == "agent_chat" and event.state in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            self._on_chat_complete()

    def _on_chat_complete(self) -> None:
        """Re-enable input after agent finishes."""
        inp = self.query_one("#input", ChatInput)
        inp.disabled = False
        inp.focus()
        # Clear activity indicator
        activity = self.query_one("#activity", ActivityBar)
        activity.clear()
        self._current_worker = None
        self._update_status()

        # Show context usage hint
        try:
            ctx_info = self.agent.get_context_info()
            pct = ctx_info["pct"]
            if pct >= 90:
                self._tui_console.print(
                    f"\n  [#F85149]Context {pct}% full — run /compact to free space[/#F85149]"
                )
            elif pct >= 70:
                self._tui_console.print(
                    f"\n  [#6E7681]Context {pct}% used "
                    f"(~{ctx_info['remaining']:,} tokens remaining)[/#6E7681]"
                )
        except Exception:
            pass

    # ── Status bar updates ─────────────────────────────────

    def _update_status(self) -> None:
        """Update status bar with current agent state."""
        statusbar = self.query_one("#statusbar", StatusBar)
        statusbar.model_name = self.config.active_model or "?"
        statusbar.mode = self.agent.mode
        try:
            ctx_info = self.agent.get_context_info()
            statusbar.ctx_pct = ctx_info.get("pct", 0)
            statusbar.ctx_remaining = ctx_info.get("remaining", 0)
            statusbar.total_tokens = getattr(self.agent, "total_tokens", 0)
        except Exception:
            pass

    def update_status_from_thread(self) -> None:
        """Thread-safe status bar update (called from agent thread)."""
        try:
            self._loop.call_soon_threadsafe(self._update_status)
        except (RuntimeError, AttributeError):
            pass

    # ── Activity bar (thread-safe, called from agent thread) ──

    def set_activity_tool(self, tool_name: str, detail: str = "") -> None:
        """Thread-safe: show tool activity like '● Read file.py'."""
        try:
            self._loop.call_soon_threadsafe(
                lambda n=tool_name, d=detail: self.query_one("#activity", ActivityBar).set_tool(n, d)
            )
        except (RuntimeError, AttributeError):
            pass

    def set_activity_thinking(self, brief: str = "") -> None:
        """Thread-safe: show thinking activity."""
        try:
            self._loop.call_soon_threadsafe(
                lambda b=brief: self.query_one("#activity", ActivityBar).set_thinking(b)
            )
        except (RuntimeError, AttributeError):
            pass

    def set_activity_progress(self, message: str, elapsed: float = 0) -> None:
        """Thread-safe: show progress like '● running command (1.2s)'."""
        try:
            self._loop.call_soon_threadsafe(
                lambda m=message, e=elapsed: self.query_one("#activity", ActivityBar).set_progress(m, e)
            )
        except (RuntimeError, AttributeError):
            pass

    def clear_activity(self) -> None:
        """Thread-safe: hide the activity bar."""
        try:
            self._loop.call_soon_threadsafe(
                lambda: self.query_one("#activity", ActivityBar).clear()
            )
        except (RuntimeError, AttributeError):
            pass

    # ── Tool confirmation (floating panel, Claude-style) ──────

    def _request_confirm(
        self,
        prompt_text: str,
        result_holder: list[str],
        result_event: threading.Event,
    ) -> None:
        """Show floating confirmation panel (always-mounted, no lifecycle bugs).

        The preview/diff is already printed to the RichLog by confirm_tool().
        This shows a Claude-style y/n/a floating panel.
        """
        self._confirm_result = result_holder
        self._confirm_event = result_event

        # Read tool info stored by confirm_tool() in rendering.py
        tool_name = getattr(self._tui_console, '_pending_confirm_tool', 'tool')
        detail = getattr(self._tui_console, '_pending_confirm_detail', '')
        # Clean up
        self._tui_console._pending_confirm_tool = None
        self._tui_console._pending_confirm_detail = None

        # Show the floating confirm panel
        panel = self.query_one("#confirm_panel", ConfirmPanel)
        panel.show_confirm(tool_name, detail)

    def on_confirm_panel_answered(self, event: ConfirmPanel.Answered) -> None:
        """Handle floating panel y/n/a answer."""
        # Log the answer
        log = self.query_one("#messages", RichLog)
        answer_map = {"y": "Accepted", "n": "Rejected", "a": "Always accept"}
        label = answer_map.get(event.answer, event.answer)
        color = {"y": "#57DB9C", "n": "#F85149", "a": "#7FA6D9"}.get(event.answer, "#8B949E")
        answer_text = Text()
        answer_text.append(f"  {label}", style=color)
        log.write(answer_text)

        # Re-focus chat input
        self.query_one("#input", ChatInput).focus()

        # Signal the worker thread
        if self._confirm_result is not None:
            self._confirm_result[0] = event.answer
        if self._confirm_event is not None:
            self._confirm_event.set()
        self._confirm_event = None
        self._confirm_result = None

    # ── Interactive selection (for /model, /skills, etc.) ──

    def show_selection(
        self,
        title: str,
        options: list[tuple[str, str]],
        active: str,
        callback: Callable[[str], None],
    ) -> None:
        """Show an interactive selection list, call *callback* with the result.

        This is non-blocking: the command handler returns immediately, and the
        actual work (e.g. ``_switch_model``) happens in *callback* when the
        user presses Enter.
        """
        if not options:
            return
        self._selection_callback = callback

        # Hide chat input + palette, show selection widget
        chat_input = self.query_one("#input", ChatInput)
        chat_input.display = False
        try:
            palette = self.query_one("#command_palette", CommandPalette)
            palette.display = False
        except Exception:
            pass

        sel = SelectionInput(title=title, options=options, active=active,
                             id="selection_input")
        self.mount(sel)
        sel.focus()

    def on_selection_input_selected(self, event: SelectionInput.Selected) -> None:
        """User picked an item from SelectionInput."""
        self._dismiss_selection()
        cb = self._selection_callback
        self._selection_callback = None
        if cb:
            cb(event.value)
        self._update_status()

    def on_selection_input_cancelled(self, event: SelectionInput.Cancelled) -> None:
        """User cancelled the SelectionInput."""
        self._dismiss_selection()
        self._selection_callback = None

    def _dismiss_selection(self) -> None:
        """Remove the SelectionInput and restore ChatInput."""
        try:
            sel = self.query_one("#selection_input", SelectionInput)
            sel.remove()
        except Exception:
            pass
        chat_input = self.query_one("#input", ChatInput)
        chat_input.display = True
        chat_input.focus()

    # ── Key bindings ───────────────────────────────────────

    def action_interrupt(self) -> None:
        """Ctrl+C: cancel current operation or ignore."""
        if self._current_worker is not None:
            self._current_worker.cancel()
            self._tui_console.print("[#E3B341]  Interrupted.[/#E3B341]")
        else:
            self._pending_ctrl_d = False

    def action_quit_app(self) -> None:
        """Ctrl+D: quit (double-tap required)."""
        if self._pending_ctrl_d:
            self._do_quit()
        else:
            self._pending_ctrl_d = True
            log = self.query_one("#messages", RichLog)
            log.write(Text("Press Ctrl-D again to exit.", style="#6E7681"))

    def action_focus_input(self) -> None:
        """Escape: focus the input box."""
        try:
            self.query_one("#input", ChatInput).focus()
        except Exception:
            pass

    def _do_quit(self) -> None:
        """Perform cleanup and exit."""
        # Flush undo history
        try:
            self.tools.files.undo.flush()
        except Exception:
            pass

        # Auto-save session
        if self.agent.conversation:
            from ..session import save_session

            auto_name = f"auto_{int(time.time())}"
            metadata = {
                "mode": self.agent.mode,
                "model": self.config.active_model,
                "project_root": str(Path(self.config.project_root).resolve()),
            }
            try:
                save_session(self.agent.conversation, auto_name, metadata)
            except Exception:
                pass

        self.exit()
