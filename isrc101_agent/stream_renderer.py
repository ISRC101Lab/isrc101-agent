"""Streaming response rendering — plain-text output, no Rich Live panel."""

import re
import time
from typing import Optional, Iterable, Tuple, Any

from rich.console import Console
from rich.status import Status

from .theme import ACCENT, DIM, WARN, SEPARATOR
from .rendering import get_icon, strip_markdown

__all__ = ["render_stream"]

_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_BLOCKQUOTE_RE = re.compile(r"(?m)^\s*>\s?")


def _compress_reasoning_line(line: str) -> str:
    compact = " ".join(line.strip().split())
    if not compact:
        return ""
    if len(compact) > 96:
        return compact[:93] + "..."
    return compact


def render_stream(
    console: Console,
    event_iterator: Iterable[Tuple[str, Any]],
    *,
    reasoning_display: str = "summary",
    llm_response_cls: Any = None,
) -> Any:
    """Stream LLM response with direct text output.

    Text chunks are written straight to stdout for zero-latency display.
    Reasoning tokens are shown via a lightweight Rich Status spinner.
    Returns an LLMResponse (or whatever llm_response_cls is).
    """
    console.print()

    response = None
    accumulated_text = ""
    accumulated_reasoning = ""
    text_started = False
    thinking_notice_shown = False
    reasoning_stream_buffer = ""
    last_reasoning_brief = ""
    thinking_status: Optional[Status] = None
    reasoning_start_time: Optional[float] = None
    reasoning_token_count = 0
    _line_buffer = ""  # buffer for line-level markdown stripping

    # ── Helpers ──────────────────────────────────

    def _write_raw(chunk: str) -> None:
        """Write a text chunk directly to the underlying stream (no processing)."""
        if not chunk:
            return
        stream = getattr(console, "file", None)
        if stream is not None and hasattr(stream, "write"):
            stream.write(chunk)
            if hasattr(stream, "flush"):
                stream.flush()
            return
        console.print(chunk, end="", markup=False, highlight=False, soft_wrap=True)

    def _write(chunk: str) -> None:
        """Buffer incoming text and flush complete lines with markdown stripped."""
        nonlocal text_started, _line_buffer
        if not chunk:
            return
        if not text_started:
            console.print()  # blank line before first output
            text_started = True
        _line_buffer += chunk
        # Flush all complete lines (strip markdown per line)
        while "\n" in _line_buffer:
            line, _line_buffer = _line_buffer.split("\n", 1)
            _write_raw(strip_markdown(line) + "\n")

    def _flush_line_buffer() -> None:
        """Flush any remaining partial line in the buffer."""
        nonlocal _line_buffer
        if _line_buffer:
            _write_raw(strip_markdown(_line_buffer))
            _line_buffer = ""

    def _stop_thinking() -> None:
        nonlocal thinking_status
        _is_tui = getattr(console, '_is_tui', False)
        if _is_tui:
            # Clear activity bar thinking indicator (non-blocking)
            try:
                console._app.clear_activity()
            except (RuntimeError, AttributeError):
                pass
            return
        if thinking_status is not None:
            thinking_status.stop()
            thinking_status = None

    def _update_thinking_display(msg: str, brief: str) -> None:
        """Shared logic for creating/updating the thinking status spinner."""
        nonlocal thinking_notice_shown, thinking_status, last_reasoning_brief, reasoning_start_time
        _is_tui = getattr(console, '_is_tui', False)

        if _is_tui:
            # TUI mode: show thinking in activity bar
            if not thinking_notice_shown:
                reasoning_start_time = time.perf_counter()
                thinking_notice_shown = True
            try:
                display_msg = brief if brief else msg
                if len(display_msg) > 60:
                    display_msg = display_msg[:57] + "..."
                console._app.set_activity_thinking(display_msg)
            except Exception:
                pass
            last_reasoning_brief = brief
            return

        # Terminal mode: use Rich Status spinner
        if not thinking_notice_shown or thinking_status is None:
            # Start timing when reasoning begins
            reasoning_start_time = time.perf_counter()
            thinking_icon = get_icon("💭")
            thinking_status = Status(
                f"  [{DIM}]{thinking_icon} {msg}[/{DIM}]",
                console=console, spinner="dots", spinner_style=ACCENT)
            thinking_status.start()
            thinking_notice_shown = True
        else:
            thinking_icon = get_icon("💭")
            thinking_status.update(f"  [{DIM}]{thinking_icon} {msg}[/{DIM}]")
        last_reasoning_brief = brief

    def _stream_reasoning(chunk: str) -> None:
        nonlocal reasoning_stream_buffer, reasoning_token_count
        if reasoning_display == "off" or not chunk:
            return

        # Track token count (rough approximation: 1 token ≈ 4 chars)
        prev_count = reasoning_token_count
        reasoning_token_count += len(chunk)

        # On first chunk, show initial "Thinking..." message with token estimate
        if prev_count == 0:
            estimated_tokens = max(100, len(chunk) // 4)
            _update_thinking_display(f"Thinking (estimated {estimated_tokens}+ tokens)...", "")

        # Process reasoning content for display
        reasoning_stream_buffer += chunk
        while "\n" in reasoning_stream_buffer:
            line, reasoning_stream_buffer = reasoning_stream_buffer.split("\n", 1)
            brief = _compress_reasoning_line(line)
            if not brief:
                continue
            if reasoning_display == "summary" and brief == last_reasoning_brief:
                continue
            msg = line.strip() if reasoning_display == "full" else brief
            _update_thinking_display(msg, brief)

    def _flush_reasoning_buffer() -> None:
        nonlocal reasoning_stream_buffer
        if reasoning_display == "off":
            reasoning_stream_buffer = ""
            return
        brief = _compress_reasoning_line(reasoning_stream_buffer)
        if not brief:
            reasoning_stream_buffer = ""
            return
        if reasoning_display == "summary" and brief == last_reasoning_brief:
            reasoning_stream_buffer = ""
            return
        msg = reasoning_stream_buffer.strip() if reasoning_display == "full" else brief
        _update_thinking_display(msg, brief)
        reasoning_stream_buffer = ""

    # ── Main event loop ──────────────────────────
    try:
        for event_type, data in event_iterator:
            if event_type == "text":
                # Strip leading newlines from first text chunk after reasoning
                # to prevent blank gap between thinking spinner and response
                if not accumulated_text and accumulated_reasoning and data:
                    data = data.lstrip("\n")
                    if not data:
                        continue
                accumulated_text += data
                _stop_thinking()
                _flush_reasoning_buffer()
                _write(data)
            elif event_type == "reasoning":
                accumulated_reasoning += data
                if not accumulated_text:
                    _stream_reasoning(data)
            elif event_type == "done":
                response = data
    except KeyboardInterrupt:
        _stop_thinking()
        if text_started:
            console.print()
        content = accumulated_text if accumulated_text else "(interrupted)"
        reasoning = accumulated_reasoning or None
        if llm_response_cls is not None:
            response = llm_response_cls(content=content, reasoning_content=reasoning)
        console.print(f"\n  [{WARN}]⚠ Stream interrupted by user[/{WARN}]")
    except ConnectionError:
        raise
    except Exception as e:
        raise ConnectionError(f"Streaming error: {type(e).__name__}: {e}")
    finally:
        _stop_thinking()
        if text_started:
            _flush_reasoning_buffer()
            _flush_line_buffer()
            console.print()  # trailing newline

        # Show reasoning summary statistics and separator
        if accumulated_reasoning and accumulated_text and reasoning_display != "off":
            reasoning_lines = accumulated_reasoning.strip().splitlines()
            reasoning_tokens = reasoning_token_count // 4  # rough estimate

            # Calculate elapsed time
            elapsed_time = 0.0
            if reasoning_start_time is not None:
                elapsed_time = time.perf_counter() - reasoning_start_time

            # Build summary line
            console.print()
            time_str = f"{elapsed_time:.1f}s" if elapsed_time > 0 else "N/A"
            thinking_icon = get_icon("💭")
            console.print(
                f"  [{SEPARATOR}]{'─' * 20}[/{SEPARATOR}] "
                f"[{DIM}]{thinking_icon} Reasoning: {reasoning_tokens} tokens, {time_str}[/{DIM}] "
                f"[{SEPARATOR}]{'─' * 20}[/{SEPARATOR}]"
            )

    if response is None:
        raise ConnectionError("Stream ended without completion")

    return response
