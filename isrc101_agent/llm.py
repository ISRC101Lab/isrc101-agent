"""LLM adapter via litellm."""

import json
from typing import List, Dict, Any, Optional, Generator, Tuple
from dataclasses import dataclass

import litellm
litellm.suppress_debug_info = True


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    usage: Optional[Dict] = None
    reasoning_content: Optional[str] = None

    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


BASE_SYSTEM_PROMPT = """\
You are isrc101-agent, an AI coding assistant running inside the user's project directory.
You help users understand, modify, and manage their codebase through natural conversation.

## Identity:
- Your name is isrc101-agent (or isrc101 for short).
- When the user asks you to introduce yourself, describe your capabilities concretely:
  what tools you have, what you can do with their codebase, and what modes are available.
- Be specific and practical, not vague or generic.

## Core workflow:
1. Explore first: list_directory and read_file before making changes.
2. Edit precisely: use str_replace for targeted edits — never rewrite entire files.
3. Verify: read the modified file or run tests after editing.
4. One step at a time: break complex tasks into small, verifiable steps.

## Rules:
- All paths are relative to the project root.
- Never access files outside the project directory.
- When str_replace fails, re-read the file and retry with the exact text.
- Briefly explain your intent before making changes.
- Respond in the same language the user uses.
"""

MODE_PROMPTS = {
    "code": BASE_SYSTEM_PROMPT,
    "ask": (
        BASE_SYSTEM_PROMPT +
        "\n\n## Mode: READ-ONLY (ask)\n"
        "You are in read-only analysis mode. You can use read_file, list_directory, and search_files "
        "to explore the codebase, but CANNOT modify files or execute commands.\n"
        "Help users understand code, find bugs, explain architecture, and suggest improvements.\n"
        "When suggesting changes, describe them clearly so the user can apply them in code mode."
    ),
    "architect": (
        BASE_SYSTEM_PROMPT +
        "\n\n## Mode: ARCHITECT\n"
        "You are in architect mode. Use read_file, list_directory, and search_files to analyze "
        "the codebase structure. Do NOT make changes.\n"
        "Focus on: design patterns, dependency analysis, refactoring plans, and architecture decisions.\n"
        "Produce clear, numbered action plans that the user can approve and execute in code mode."
    ),
}


def build_system_prompt(mode: str, project_instructions: Optional[str] = None) -> str:
    prompt = MODE_PROMPTS.get(mode, MODE_PROMPTS["code"])
    if project_instructions:
        prompt += f"\n\n## Project instructions (AGENT.md):\n{project_instructions}"
    return prompt


class LLMAdapter:
    """Unified LLM interface. Passes api_key/api_base directly to litellm,
    avoiding env-var pollution when switching between providers."""

    def __init__(self, model: str, temperature: float = 0.0,
                 max_tokens: int = 4096, api_base: Optional[str] = None,
                 api_key: Optional[str] = None, context_window: int = 128000):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.api_base = api_base
        self.api_key = api_key
        self.context_window = context_window

    @property
    def is_thinking_model(self) -> bool:
        """Whether this model uses thinking/reasoning mode.
        Covers DeepSeek Reasoner and Qwen3-VL-*-Thinking models."""
        m = self.model.lower()
        return "reasoner" in m or "thinking" in m

    def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict]] = None) -> LLMResponse:
        kwargs: Dict[str, Any] = {
            "model": self.model, "messages": messages,
            "temperature": self.temperature, "max_tokens": self.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key

        try:
            response = litellm.completion(**kwargs)
        except litellm.exceptions.AuthenticationError as e:
            raise ConnectionError(f"Auth failed. Check API key.\n{e}")
        except litellm.exceptions.APIConnectionError as e:
            raise ConnectionError(f"Cannot connect: model={self.model}, base={self.api_base or 'default'}\n{e}")
        except Exception as e:
            raise ConnectionError(f"LLM error: {type(e).__name__}: {e}")

        choice = response.choices[0]
        msg = choice.message

        tool_calls = None
        if msg.tool_calls:
            tool_calls = []
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        usage = None
        if response.usage:
            usage = {"prompt_tokens": response.usage.prompt_tokens,
                     "completion_tokens": response.usage.completion_tokens,
                     "total_tokens": response.usage.total_tokens}

        # Capture reasoning_content for DeepSeek Reasoner multi-turn.
        # The API REQUIRES this field on every assistant message in subsequent turns.
        reasoning_content = getattr(msg, "reasoning_content", None)
        if reasoning_content is None and self.is_thinking_model:
            reasoning_content = ""  # Thinking models always need this field, even if empty

        return LLMResponse(content=msg.content, tool_calls=tool_calls,
                           usage=usage, reasoning_content=reasoning_content)

    def chat_stream(self, messages: List[Dict[str, Any]],
                    tools: Optional[List[Dict]] = None
                    ) -> Generator[Tuple[str, Any], None, None]:
        """Streaming chat. Yields (event_type, data) tuples.

        Event types:
          "text"      — str: incremental text content
          "reasoning" — str: incremental reasoning content (DeepSeek Reasoner)
          "done"      — LLMResponse: final complete response

        Falls back to non-streaming on failure.
        """
        kwargs: Dict[str, Any] = {
            "model": self.model, "messages": messages,
            "temperature": self.temperature, "max_tokens": self.max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key

        # Try streaming; fall back to non-streaming on failure
        try:
            response_stream = litellm.completion(**kwargs)
        except Exception:
            # Fallback: non-streaming
            response = self.chat(messages, tools)
            if response.content:
                yield ("text", response.content)
            yield ("done", response)
            return

        full_content = ""
        reasoning_parts = ""
        tc_data: Dict[int, Dict[str, str]] = {}
        usage = None

        try:
            for chunk in response_stream:
                # Usage-only final chunk (some providers)
                if not chunk.choices:
                    if hasattr(chunk, "usage") and chunk.usage:
                        usage = {"prompt_tokens": chunk.usage.prompt_tokens,
                                 "completion_tokens": chunk.usage.completion_tokens,
                                 "total_tokens": chunk.usage.total_tokens}
                    continue

                delta = chunk.choices[0].delta

                # Text
                if getattr(delta, "content", None):
                    full_content += delta.content
                    yield ("text", delta.content)

                # Reasoning (DeepSeek Reasoner)
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning_parts += rc
                    yield ("reasoning", rc)

                # Tool calls (accumulated across chunks)
                if getattr(delta, "tool_calls", None):
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tc_data:
                            tc_data[idx] = {"id": "", "name": "", "args": ""}
                        if tc_delta.id:
                            tc_data[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tc_data[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tc_data[idx]["args"] += tc_delta.function.arguments

                # Usage from chunk
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = {"prompt_tokens": chunk.usage.prompt_tokens,
                             "completion_tokens": chunk.usage.completion_tokens,
                             "total_tokens": chunk.usage.total_tokens}
        except Exception as e:
            raise ConnectionError(f"Stream interrupted: {type(e).__name__}: {e}")

        # Build tool calls
        tool_calls = None
        if tc_data:
            tool_calls = []
            for idx in sorted(tc_data.keys()):
                tc = tc_data[idx]
                try:
                    args = json.loads(tc["args"])
                except json.JSONDecodeError:
                    args = {"_raw": tc["args"]}
                tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], arguments=args))

        # Reasoning content for reasoner models
        reasoning_content = reasoning_parts if reasoning_parts else None
        if reasoning_content is None and self.is_thinking_model:
            reasoning_content = ""

        yield ("done", LLMResponse(
            content=full_content or None,
            tool_calls=tool_calls,
            usage=usage,
            reasoning_content=reasoning_content,
        ))
