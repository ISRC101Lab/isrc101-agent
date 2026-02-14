"""Tests for stream_renderer — especially think tag blank-line fix."""

import io
from dataclasses import dataclass
from typing import Optional, List, Any

import pytest

from rich.console import Console


@dataclass
class MockLLMResponse:
    content: str = ""
    reasoning_content: Optional[str] = None
    tool_calls: Optional[List] = None
    usage: Optional[dict] = None

    def has_tool_calls(self):
        return bool(self.tool_calls)


def _make_events(reasoning_chunks=None, text_chunks=None):
    """Build a (event_type, data) iterator simulating LLM streaming."""
    events = []
    if reasoning_chunks:
        for chunk in reasoning_chunks:
            events.append(("reasoning", chunk))
    if text_chunks:
        for chunk in text_chunks:
            events.append(("text", chunk))
    response = MockLLMResponse(
        content="".join(text_chunks or []),
        reasoning_content="".join(reasoning_chunks or []) if reasoning_chunks else None,
    )
    events.append(("done", response))
    return events


class TestStreamRendererBlankLineFix:
    """The first text chunk after reasoning should not start with blank lines."""

    def test_no_leading_newlines_after_reasoning(self):
        from isrc101_agent.stream_renderer import render_stream

        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, width=120)

        events = _make_events(
            reasoning_chunks=["Let me think...\n", "Step 1: analyze\n"],
            text_chunks=["\n\nHere is the answer."],
        )

        response = render_stream(
            console,
            iter(events),
            reasoning_display="summary",
            llm_response_cls=MockLLMResponse,
        )

        output = buf.getvalue()
        # The answer should appear without excessive blank lines
        assert "Here is the answer." in output
        # Should not have 3+ consecutive blank lines
        assert "\n\n\n\n" not in output

    def test_text_only_no_stripping(self):
        from isrc101_agent.stream_renderer import render_stream

        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, width=120)

        events = _make_events(
            reasoning_chunks=None,
            text_chunks=["Hello world."],
        )

        response = render_stream(
            console,
            iter(events),
            reasoning_display="summary",
            llm_response_cls=MockLLMResponse,
        )

        output = buf.getvalue()
        assert "Hello world." in output

    def test_reasoning_only_chunks_stripped(self):
        """If text chunk is only newlines after reasoning, it should be skipped."""
        from isrc101_agent.stream_renderer import render_stream

        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, width=120)

        events = _make_events(
            reasoning_chunks=["Thinking..."],
            text_chunks=["\n\n", "Real content here."],
        )

        response = render_stream(
            console,
            iter(events),
            reasoning_display="summary",
            llm_response_cls=MockLLMResponse,
        )

        output = buf.getvalue()
        assert "Real content here." in output
