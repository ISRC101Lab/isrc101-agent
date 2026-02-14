"""LLM adapter via litellm."""

import json
import random
import time
import threading
from typing import List, Dict, Any, Optional, Generator, Tuple
from dataclasses import dataclass

from importlib import import_module

_LITELLM = None


def _get_litellm():
    """Lazily import litellm to avoid slow CLI startup."""
    global _LITELLM
    if _LITELLM is None:
        module = import_module("litellm")
        module.suppress_debug_info = True
        _LITELLM = module
    return _LITELLM

from .logger import get_logger

_log = get_logger(__name__)

__all__ = ["LLMAdapter", "LLMResponse", "ToolCall", "build_system_prompt"]


# Retry defaults for transient LLM/API failures.
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0
RETRY_BACKOFF_FACTOR = 2.0
MAX_RETRY_DELAY = 30.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503}


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
  what tools you have and what you can do with their codebase.
- Be specific and practical, not vague or generic.

## Core workflow:
1. Only use tools when the user asks a task-related question. For greetings or casual chat, respond directly without calling any tools.
2. Explore first: list_directory and read_file before making changes to code.
3. Edit precisely: use str_replace for targeted edits — never rewrite entire files.
4. Verify: read the modified file or run tests after editing.
5. One step at a time: break complex tasks into small, verifiable steps.
6. Prefer batching independent read-only tool calls in a single assistant turn to minimize round trips.

## Output format:
- Your output will be displayed on a command line interface in a monospace font.
- Do NOT use any markdown formatting in your responses. No **, ##, `, >, - lists, or ``` fencing.
- Write plain text only. Use blank lines to separate paragraphs and sections.
- For code examples, write the code directly with proper indentation. Do not wrap in backticks or code fences.
- Use plain text for emphasis (e.g. write "IMPORTANT:" instead of **important**).
- Use simple numbered lists (1. 2. 3.) or dashes followed by a space for bullet points.
- Never use markdown headers (# ## ###). Use UPPERCASE or a plain label followed by a colon for section titles.

## Rules:
- All paths are relative to the project root.
- Never access files outside the project directory.
- When str_replace fails, re-read the file and retry with the exact text.
- Briefly explain your intent before making changes.
- Respond in the same language the user uses.
- If multiple independent checks are needed, emit multiple tool calls together instead of serial single-tool turns.

## Available tools:
- read_file, create_file, write_file, append_file, str_replace, delete_file: File operations
  - For large files (>150 lines): use create_file for the first chunk, then append_file to add remaining chunks.
- list_directory, search_files, find_files, find_symbol: Explore codebase
  - find_files: glob pattern matching (e.g. '*.py', 'test_*') — use to discover files
  - find_symbol: locate function/class definitions by name — faster than search_files for definitions
  - search_files: regex content search with optional context lines — use for content matching
- bash: Execute shell commands
- read_image: Analyze images (PNG, JPG, etc.)
- web_fetch: Fetch a URL and return clean markdown content (only when web is enabled)
- web_search: Search the web for information (only when web is enabled)
- crew_execute: Launch multi-agent crew for complex tasks — automatically decomposes, assigns specialist roles, executes in parallel

## Multi-agent collaboration (crew_execute):
- You have a built-in multi-agent crew system. Call the crew_execute tool when a task is complex enough to benefit from parallel specialist work.
- When to use crew_execute:
  - Tasks involving multiple steps across different concerns (e.g. "add a feature, write tests, and review code quality").
  - Tasks that benefit from parallel execution by different roles.
  - Large refactoring or feature implementation that spans multiple files.
- When NOT to use crew_execute:
  - Simple single-file edits, quick fixes, or questions.
  - Tasks you can complete in 1-3 tool calls.
  - Pure analysis or explanation requests.
- When you call crew_execute, the system automatically:
  1. Decomposes the task into subtasks with dependency analysis.
  2. Assigns each subtask to a specialized role (coder, reviewer, researcher, tester).
  3. Runs multiple instances of the same role in parallel when there are independent tasks.
  4. Optionally runs code review loops: reviewer checks coder output, requests rework if needed.
  5. Synthesizes all results into a unified summary.
- Four built-in roles:
  - coder: writes and modifies code (agent mode, no web access).
  - reviewer: reviews code for correctness, security, and style (read-only mode).
  - researcher: gathers technical information and documentation (read-only mode, web enabled).
  - tester: writes and runs tests (agent mode).
- Token budget is shared across all agents to prevent runaway cost.

## Web search strategy (when web is enabled):
- **IMPORTANT: Not every question needs a web search.** Use web search ONLY when the question genuinely requires up-to-date or external information, such as:
  - Latest versions, release dates, recent news, or current events
  - Specific URLs the user wants you to fetch
  - Niche technical details you are not confident about
  - Questions that explicitly ask about "latest", "newest", "current" information
- **Do NOT use web search for:**
  - Common knowledge and well-established concepts (e.g. "what is CUDA", "explain TCP/IP", "how does git rebase work")
  - General programming help, code review, debugging, or refactoring
  - Questions about the user's own codebase (use file tools instead)
  - Opinions, best practices, or architectural advice you can answer from training data
- When in doubt, answer directly first. Only search if you genuinely lack the knowledge.
- **Query formulation is critical.** NEVER pass the user's raw question as the search query. Instead:
  1. Extract 3-6 key terms from the user's question.
  2. Remove filler words, pronouns, and conversational phrases.
  3. Use English keywords even if the user asks in Chinese — search engines work better with English.
  4. Example: User asks "CUDA最新版本支持哪些新特性?" → search query: "CUDA latest version new features release notes"
  5. Example: User asks "怎么在PyTorch中使用混合精度训练?" → search query: "PyTorch mixed precision training AMP tutorial"
- **Never assume version numbers or "latest" from your training data.** Your knowledge has a cutoff date and may be outdated.
- When the user asks about "latest", "newest", "current" versions or recent information:
  1. First use web_search with a neutral query (e.g. "NVIDIA PTX ISA latest version" instead of "PTX 8.7").
  2. If search results mention an official URL, use web_fetch on that URL to get authoritative details.
  3. **Focus on the version you discovered, not older versions.** Do not pad your response with summaries of previous releases unless the user explicitly asks for a changelog or comparison.
- **CRITICAL: When web_fetch or web_search returns content, your response MUST be based strictly on the fetched content.** Do not mix in or substitute information from your training data. If the fetched page says feature X was added, report feature X — do not replace it with feature Y from your memory. Quote or closely paraphrase the source.
- After web_fetch returns content, **extract and present specific details** (new features, API changes, concrete examples) rather than vague one-line summaries.
- When the user provides a specific URL, fetch it directly with web_fetch — no need to search first.
- Avoid redundant fetches: do not fetch the same URL twice in one conversation.
- Prefer official/authoritative sources (docs, release notes, changelogs) over blog posts or forums.
- **One search round is usually enough.** Do not do follow-up searches for older versions or tangential topics unless the user asks.
- **Never use bash/curl/wget for web requests.** Always use web_fetch or web_search instead — they produce cleaner output and respect the web display settings.
- **Minimize tool call rounds.** Typical web query flow: web_search → web_fetch (if needed) → respond. Avoid unnecessary verification steps like curl-checking whether a newer version exists.
- **NEVER repeat the same web_search query or web_fetch URL.** If you already searched or fetched something, use the cached result. Do not loop.
- **If evidence is insufficient, say so honestly.** Never fabricate information, version numbers, dates, or URLs. Say "I could not find reliable information on this" rather than guessing.
- **Do not mix training data with web results.** If the web search returned specific facts, use those facts only. Do not supplement with information from your training data unless clearly labeled as such.
- When strict web grounding is active, output only the exact structured payload requested by the system for verification.
"""

MODE_PROMPTS = {
    "agent": BASE_SYSTEM_PROMPT,
    "ask": (
        BASE_SYSTEM_PROMPT
        + "\n\n## Mode: READ-ONLY (ask)\n"
        + "You are in read-only analysis mode. Do not modify files or execute shell commands. "
        + "Focus on explanation, diagnosis, and actionable suggestions."
    ),
}


def build_system_prompt(mode: str = "agent",
                        skill_instructions: Optional[str] = None,
                        answer_style: str = "concise") -> str:
    normalized_mode = str(mode or "agent").strip().lower()
    if normalized_mode in ("code", "architect"):
        normalized_mode = "agent"
    prompt = MODE_PROMPTS.get(normalized_mode, MODE_PROMPTS["agent"])

    style = str(answer_style or "concise").strip().lower()
    style_prompts = {
        "concise": (
            "\n\n## Response style: CONCISE\n"
            "- Keep answers short and actionable by default.\n"
            "- Use plain text, no markdown formatting.\n"
            "- Avoid repetition and generic filler.\n"
            "- For simple questions, answer in 1-4 lines.\n"
            "- Expand only when the user explicitly asks for detail."
        ),
        "balanced": (
            "\n\n## Response style: BALANCED\n"
            "- Be clear and practical with moderate detail.\n"
            "- Use plain text, no markdown formatting.\n"
            "- Include key rationale without over-explaining."
        ),
        "detailed": (
            "\n\n## Response style: DETAILED\n"
            "- Provide thorough explanations and trade-offs when helpful.\n"
            "- Use plain text, no markdown formatting."
        ),
    }
    prompt += style_prompts.get(style, style_prompts["concise"])

    if skill_instructions:
        prompt += f"\n\n{skill_instructions}"
    return prompt


class LLMAdapter:
    """Unified LLM interface. Passes api_key/api_base directly to litellm,
    avoiding env-var pollution when switching between providers."""

    def __init__(self, model: str, temperature: float = 0.0,
                 max_tokens: int = 8192, api_base: Optional[str] = None,
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

    def _is_litellm_exception(self, error: Exception, *names: str) -> bool:
        """Safely check litellm exception classes by name."""
        for name in names:
            litellm_module = _get_litellm()
            exc_type = getattr(litellm_module.exceptions, name, None)
            if exc_type and isinstance(error, exc_type):
                return True
        return False

    def _extract_status_code(self, error: Exception) -> Optional[int]:
        """Extract HTTP status code from different exception shapes."""
        candidates = [
            getattr(error, "status_code", None),
            getattr(error, "http_status", None),
            getattr(error, "status", None),
        ]

        response = getattr(error, "response", None)
        if response is not None:
            candidates.append(getattr(response, "status_code", None))

        for value in candidates:
            try:
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                continue

        return None

    def _is_timeout_error(self, error: Exception) -> bool:
        """Match timeout exceptions from litellm and common HTTP clients."""
        if isinstance(error, TimeoutError):
            return True

        if self._is_litellm_exception(error, "Timeout"):
            return True

        name = type(error).__name__.lower()
        if "timeout" in name:
            return True

        message = str(error).lower()
        return "timed out" in message or "timeout" in message

    def _is_retryable_error(self, error: Exception) -> bool:
        """Return True only for transient/retry-safe error types."""
        if self._is_litellm_exception(error, "AuthenticationError"):
            return False

        if isinstance(error, ConnectionError):
            return True

        if self._is_litellm_exception(error, "APIConnectionError", "RateLimitError"):
            return True

        if self._is_timeout_error(error):
            return True

        status_code = self._extract_status_code(error)
        if status_code in RETRYABLE_STATUS_CODES:
            return True

        message = str(error).lower()
        return "rate limit" in message

    def _log_retry(self, attempt: int) -> None:
        _log.info("Retrying (attempt %d/%d)...", attempt, MAX_RETRIES)

    def _next_retry_delay(self, delay: float) -> float:
        """Apply jitter and exponential backoff, capped at MAX_RETRY_DELAY."""
        jitter = random.uniform(0, max(0.1, delay * 0.25))
        sleep_seconds = min(delay + jitter, MAX_RETRY_DELAY)
        time.sleep(sleep_seconds)
        return min(delay * RETRY_BACKOFF_FACTOR, MAX_RETRY_DELAY)

    def _raise_chat_error(self, error: Exception) -> None:
        if self._is_litellm_exception(error, "AuthenticationError"):
            raise ConnectionError(f"Auth failed. Check API key.\n{error}") from error
        if self._is_litellm_exception(error, "APIConnectionError"):
            base = self.api_base or "default"
            raise ConnectionError(
                f"Cannot connect: model={self.model}, base={base}\n{error}"
            ) from error
        raise ConnectionError(f"LLM error: {type(error).__name__}: {error}") from error

    def warmup(self) -> bool:
        """Synchronously warm up heavy LLM dependencies."""
        try:
            _get_litellm()
            return True
        except Exception:
            return False

    def warmup_async(self) -> None:
        """Warm up LLM dependencies in background without blocking startup."""
        thread = threading.Thread(target=self.warmup, daemon=True, name="llm-warmup")
        thread.start()

    def _completion_with_retry(self, kwargs: Dict[str, Any], max_retries: Optional[int] = None) -> Any:
        """Run litellm.completion with retry for transient errors."""
        budget = max_retries if max_retries is not None else MAX_RETRIES
        delay = INITIAL_RETRY_DELAY

        for retry_index in range(budget + 1):
            try:
                litellm_module = _get_litellm()
                return litellm_module.completion(**kwargs)
            except Exception as e:
                if retry_index < budget and self._is_retryable_error(e):
                    self._log_retry(retry_index + 1)
                    delay = self._next_retry_delay(delay)
                    continue
                self._raise_chat_error(e)

        # Defensive fallback; loop always returns or raises.
        raise ConnectionError("LLM request failed after retries")

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

        response = self._completion_with_retry(kwargs)

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
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key

        delay = INITIAL_RETRY_DELAY
        last_error: Optional[Exception] = None
        retries_consumed = 0

        for retry_index in range(MAX_RETRIES + 1):
            full_content = ""
            reasoning_parts = ""
            tc_data: Dict[int, Dict[str, Any]] = {}
            usage = None

            try:
                litellm_module = _get_litellm()
                response_stream = litellm_module.completion(**kwargs)

                for chunk in response_stream:
                    # Usage-only final chunk (some providers)
                    if not chunk.choices:
                        if hasattr(chunk, "usage") and chunk.usage:
                            usage = {
                                "prompt_tokens": chunk.usage.prompt_tokens,
                                "completion_tokens": chunk.usage.completion_tokens,
                                "total_tokens": chunk.usage.total_tokens,
                            }
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
                            if idx is None:
                                continue
                            if idx not in tc_data:
                                tc_data[idx] = {"id": "", "name": "", "args": []}
                            if tc_delta.id:
                                tc_data[idx]["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    tc_data[idx]["name"] = tc_delta.function.name
                                if tc_delta.function.arguments:
                                    tc_data[idx]["args"].append(tc_delta.function.arguments)

                    # Usage from chunk
                    if hasattr(chunk, "usage") and chunk.usage:
                        usage = {
                            "prompt_tokens": chunk.usage.prompt_tokens,
                            "completion_tokens": chunk.usage.completion_tokens,
                            "total_tokens": chunk.usage.total_tokens,
                        }

                # Build tool calls
                tool_calls = None
                if tc_data:
                    tool_calls = []
                    for idx in sorted(tc_data.keys()):
                        tc = tc_data[idx]
                        args_str = "".join(tc["args"])
                        try:
                            args = json.loads(args_str)
                        except json.JSONDecodeError:
                            args = {"_raw": args_str}
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
                return
            except Exception as e:
                last_error = e
                has_partial_stream = bool(full_content or reasoning_parts or tc_data)

                # Only retry if the stream failed before emitting a partial response.
                if (
                    retry_index < MAX_RETRIES
                    and self._is_retryable_error(e)
                    and not has_partial_stream
                ):
                    self._log_retry(retry_index + 1)
                    delay = self._next_retry_delay(delay)
                    retries_consumed = retry_index + 1
                    continue

                if has_partial_stream:
                    raise ConnectionError(f"Stream interrupted: {type(e).__name__}: {e}") from e
                retries_consumed = retry_index
                break

        # Final fallback: non-streaming with remaining retry budget
        if last_error is not None and self._is_litellm_exception(last_error, "AuthenticationError"):
            self._raise_chat_error(last_error)

        remaining = max(0, MAX_RETRIES - retries_consumed)
        _log.warning(
            "Streaming failed after %d attempt(s) (%s); falling back to non-streaming (remaining retries: %d)",
            retries_consumed + 1,
            type(last_error).__name__ if last_error else "unknown",
            remaining,
        )

        kwargs_non_stream = {k: v for k, v in kwargs.items() if k != "stream"}
        response = self._completion_with_retry(kwargs_non_stream, max_retries=remaining)

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

        reasoning_content = getattr(msg, "reasoning_content", None)
        if reasoning_content is None and self.is_thinking_model:
            reasoning_content = ""

        llm_response = LLMResponse(content=msg.content, tool_calls=tool_calls,
                                   usage=usage, reasoning_content=reasoning_content)
        if llm_response.content:
            yield ("text", llm_response.content)
        yield ("done", llm_response)
