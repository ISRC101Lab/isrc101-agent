"""Tests for empty/reasoning-only LLM response handling in Agent.chat()."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


@dataclass
class FakeLLMResponse:
    content: Optional[str] = None
    reasoning_content: Optional[str] = None
    tool_calls: Optional[List] = None
    usage: Optional[Dict[str, int]] = None

    def has_tool_calls(self):
        return bool(self.tool_calls)


class FakeLLM:
    """LLM stub that returns a sequence of pre-set responses."""

    def __init__(self, responses: List[FakeLLMResponse]):
        self._responses = list(responses)
        self._call_count = 0
        # Required attributes for Agent init
        self.model = "test-model"
        self.max_tokens = 4096
        self.context_window = 128000
        self.is_thinking_model = False

    def chat(self, messages, tools=None):
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        return self._responses[idx]

    def chat_stream(self, messages, tools=None):
        resp = self.chat(messages, tools)
        if resp.reasoning_content:
            yield ("reasoning", resp.reasoning_content)
        if resp.content:
            yield ("text", resp.content)
        yield ("done", resp)

    def warmup_async(self):
        pass


def _make_agent(llm):
    """Create an Agent with minimal mocking."""
    from isrc101_agent.agent import Agent

    tools = MagicMock()
    tools.schemas = []
    tools.git = MagicMock()
    tools.git.available = False

    agent = Agent(
        llm=llm,
        tools=tools,
        auto_confirm=True,
        chat_mode="ask",
        skill_instructions="",
    )
    agent.quiet = True
    return agent


class TestEmptyResponseHandling:
    """Agent.chat() handles empty and reasoning-only responses correctly."""

    def test_truly_empty_response_stops_after_max(self):
        """Truly empty responses (no content, no reasoning) stop after _MAX_EMPTY."""
        responses = [FakeLLMResponse() for _ in range(10)]
        llm = FakeLLM(responses)
        agent = _make_agent(llm)

        result = agent.chat("hello")
        assert "consecutive empty responses" in result.lower() or "stopping" in result.lower()

    def test_reasoning_only_uses_fallback(self):
        """Reasoning-only responses eventually return reasoning as fallback."""
        responses = [
            FakeLLMResponse(reasoning_content="I need to think about this carefully.")
            for _ in range(10)
        ]
        llm = FakeLLM(responses)
        agent = _make_agent(llm)

        result = agent.chat("hello")
        # Should return reasoning as fallback, not the "Stopping" message
        assert "think about this carefully" in result

    def test_reasoning_only_adds_nudge_messages(self):
        """On reasoning-only, nudge messages are added to conversation."""
        responses = [
            FakeLLMResponse(reasoning_content="Let me consider..."),
            FakeLLMResponse(content="Here is my answer."),  # Succeeds on 2nd try
        ]
        llm = FakeLLM(responses)
        agent = _make_agent(llm)

        result = agent.chat("hello")
        assert result == "Here is my answer."
        # Conversation should contain the nudge
        texts = [m.get("content", "") for m in agent.conversation]
        assert any("provide your actual response" in t for t in texts)

    def test_empty_then_content_resets_streak(self):
        """Content response after empty resets the streak."""
        responses = [
            FakeLLMResponse(),  # empty #1
            FakeLLMResponse(content="Got it!"),  # success
        ]
        llm = FakeLLM(responses)
        agent = _make_agent(llm)

        result = agent.chat("hello")
        # The empty response doesn't add nudge (no reasoning), but the retry
        # with same prompt may succeed
        assert result == "Got it!"

    def test_tool_call_resets_empty_streak(self):
        """Tool calls between empty responses reset the streak counter."""
        from isrc101_agent.llm import ToolCall

        tc = ToolCall(id="tc1", name="read_file", arguments={"path": "test.txt"})
        responses = [
            FakeLLMResponse(tool_calls=[tc]),
            FakeLLMResponse(content="Done reading."),
        ]
        llm = FakeLLM(responses)
        agent = _make_agent(llm)
        # Mock tool execution
        agent.tools.execute = MagicMock(return_value="file content")
        agent.tools.can_parallelize = MagicMock(return_value=False)

        result = agent.chat("read test.txt")
        assert "Done reading" in result

    def test_max_empty_increased_to_five(self):
        """_MAX_EMPTY should be 5, giving more retry chances with nudges."""
        responses = [FakeLLMResponse() for _ in range(10)]
        llm = FakeLLM(responses)
        agent = _make_agent(llm)

        agent.chat("hello")
        # Should have made 5 calls (not 3)
        assert llm._call_count == 5

    def test_reasoning_fallback_added_to_conversation(self):
        """When reasoning fallback is used, it's added to conversation history."""
        responses = [
            FakeLLMResponse(reasoning_content="Deep analysis here.")
            for _ in range(10)
        ]
        llm = FakeLLM(responses)
        agent = _make_agent(llm)

        result = agent.chat("analyze this")
        # Check the fallback was stored in conversation
        assistant_msgs = [m for m in agent.conversation if m["role"] == "assistant"]
        assert any("Deep analysis" in m["content"] for m in assistant_msgs)
