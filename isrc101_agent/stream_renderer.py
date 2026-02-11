"""Streaming response rendering — plain-text output, no Rich Live panel."""

import re
from typing import Optional, Iterable, Tuple, Any

from rich.console import Console
from rich.status import Status

from .theme import ACCENT, DIM, WARN, SEPARATOR

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
    width = console.width or 120
    separator = "─" * width
    console.print()
    console.print(f"[{SEPARATOR}]{separator}[/{SEPARATOR}]")

    response = None
    accumulated_text = ""
    accumulated_reasoning = ""
    text_started = False
    thinking_notice_shown = False
    reasoning_stream_buffer = ""
    last_reasoning_brief = ""
    thinking_status: Optional[Status] = None

    # ── Helpers ──────────────────────────────────

    def _write(chunk: str) -> None:
        """Write a text chunk directly to the underlying stream."""
        nonlocal text_started
        if not chunk:
            return
        if not text_started:
            console.print()  # blank line before first output
            text_started = True
        stream = getattr(console, "file", None)
        if stream is not None and hasattr(stream, "write"):
            stream.write(chunk)
            if hasattr(stream, "flush"):
                stream.flush()
            return
        console.print(chunk, end="", markup=False, highlight=False, soft_wrap=True)

    def _stop_thinking() -> None:
        nonlocal thinking_status
        if thinking_status is not None:
            thinking_status.stop()
            thinking_status = None

    def _update_thinking_display(msg: str, brief: str) -> None:
        """Shared logic for creating/updating the thinking status spinner."""
        nonlocal thinking_notice_shown, thinking_status, last_reasoning_brief
        if not thinking_notice_shown or thinking_status is None:
            thinking_status = Status(
                f"  [{DIM}]💭 {msg}[/{DIM}]",
                console=console, spinner="dots", spinner_style=ACCENT)
            thinking_status.start()
            thinking_notice_shown = True
        else:
            thinking_status.update(f"  [{DIM}]💭 {msg}[/{DIM}]")
        last_reasoning_brief = brief

    def _stream_reasoning(chunk: str) -> None:
        nonlocal reasoning_stream_buffer
        if reasoning_display == "off" or not chunk:
            return
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
        reasoning = accumulated_reasoning if accumulated_reasoning else None
        if reasoning is not None and not reasoning:
            reasoning = ""
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
            console.print()  # trailing newline

        if accumulated_reasoning and accumulated_text:
            reasoning_lines = accumulated_reasoning.strip().splitlines()
            if reasoning_display != "off" and len(reasoning_lines) > 3:
                console.print()
                console.print(
                    f"  [{SEPARATOR}]───[/{SEPARATOR}] "
                    f"[{DIM}]💭 {len(reasoning_lines)} lines of reasoning[/{DIM}] "
                    f"[{SEPARATOR}]───[/{SEPARATOR}]"
                )

        # Bottom separator line
        console.print(f"[{SEPARATOR}]{separator}[/{SEPARATOR}]")

    if response is None:
        raise ConnectionError("Stream ended without completion")

    return response
