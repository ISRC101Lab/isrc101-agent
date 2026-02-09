"""Core agent loop with clear visual distinction between user and agent output."""

import json
import re
import time
from typing import List, Dict, Any, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.live import Live

from .llm import LLMAdapter, LLMResponse, build_system_prompt
from .tools import ToolRegistry
from .logger import get_logger
from .tokenizer import estimate_tokens, estimate_message_tokens

_log = get_logger(__name__)
console = Console()

__all__ = ["Agent"]

# ── Visual theme ───────────────────────────────────
AGENT_BORDER = "cyan"
AGENT_LABEL = "[bold cyan]isrc101[/bold cyan]"
TOOL_BORDER = "dim"


class Agent:
    STREAM_PROFILES = {
        "stable": {
            "interval": 0.08,
            "min_chars": 20,
            "priority_interval": 0.025,
            "priority_chars": 6,
            "max_silent_ms": 300,
        },
        "smooth": {
            "interval": 0.06,
            "min_chars": 12,
            "priority_interval": 0.015,
            "priority_chars": 3,
            "max_silent_ms": 250,
        },
        "ultra": {
            "interval": 0.04,
            "min_chars": 4,
            "priority_interval": 0.008,
            "priority_chars": 1,
            "max_silent_ms": 200,
        },
    }

    def __init__(self, llm: LLMAdapter, tools: ToolRegistry, max_iterations: int = 30,
                 auto_confirm: bool = False, chat_mode: str = "code",
                 auto_commit: bool = True,
                 skill_instructions: Optional[str] = None,
                 reasoning_display: str = "summary",
                 web_display: str = "summary",
                 answer_style: str = "concise",
                 stream_profile: str = "ultra",
                 web_preview_lines: int = 3,
                 web_preview_chars: int = 360,
                 web_context_chars: int = 4000):
        self.llm = llm
        self.tools = tools
        self.max_iterations = max_iterations
        self.auto_confirm = auto_confirm
        self.auto_commit = auto_commit
        self.skill_instructions = skill_instructions
        self.reasoning_display = reasoning_display
        self.web_display = web_display
        self.answer_style = answer_style
        self._stream_profile = "ultra"
        self.stream_profile = stream_profile
        self.web_preview_lines = max(1, int(web_preview_lines))
        self.web_preview_chars = max(80, int(web_preview_chars))
        self.web_context_chars = max(500, int(web_context_chars))
        self._mode = chat_mode
        self.tools.mode = chat_mode
        self.conversation: List[Dict[str, Any]] = []
        self.total_tokens = 0
        self._files_modified = False

    @property
    def mode(self):
        return self._mode

    @mode.setter
    def mode(self, value):
        if value in ("code", "ask", "architect"):
            self._mode = value
            self.tools.mode = value

    @property
    def stream_profile(self) -> str:
        return self._stream_profile

    @stream_profile.setter
    def stream_profile(self, value: str):
        profile = str(value or "ultra").strip().lower()
        if profile not in self.STREAM_PROFILES:
            profile = "ultra"
        self._stream_profile = profile

    def _stream_profile_setting(self, key: str):
        return self.STREAM_PROFILES[self._stream_profile][key]

    def chat(self, user_message: str) -> str:
        self.conversation.append({"role": "user", "content": user_message})
        self._files_modified = False
        system = build_system_prompt(
            self._mode,
            self.skill_instructions,
            self.answer_style,
        )

        for _ in range(self.max_iterations):
            messages = self._prepare_messages(system)

            try:
                response = self._stream_response(messages)
            except ConnectionError as e:
                _log.error("Connection error: %s", e)
                self._render_error(str(e))
                return str(e)

            if response.usage:
                self.total_tokens += response.usage.get("total_tokens", 0)

            if response.has_tool_calls():
                self._handle_tool_calls(response)
                continue

            if response.content:
                assistant_msg = {"role": "assistant", "content": response.content}
                if response.reasoning_content is not None:
                    assistant_msg["reasoning_content"] = response.reasoning_content
                self.conversation.append(assistant_msg)
                # Rendering already done by _stream_response
                if self._files_modified and self.auto_commit and self.tools.git.available:
                    commit_hash = self.tools.git.auto_commit()
                    if commit_hash:
                        console.print(f"  [dim]📦 committed: {commit_hash}[/dim]")
                    elif self.tools.git.has_changes():
                        console.print("  [yellow]⚠ auto-commit skipped (check git status)[/yellow]")
                return response.content

            console.print("[dim]  (empty response, retrying...)[/dim]")

        msg = f"⚠ Reached max iterations ({self.max_iterations})."
        console.print(f"\n[yellow]{msg}[/yellow]")
        return msg

    # ── Context window management ──────────────

    def _estimate_tokens(self, text: str) -> int:
        """Token estimate using tiktoken when available."""
        return estimate_tokens(text, self.llm.model)

    def _estimate_message_tokens(self, msg: dict) -> int:
        """Estimate tokens for a conversation message."""
        return estimate_message_tokens(msg, self.llm.model)

    def _assistant_tool_call_ids(self, msg: Dict[str, Any]) -> List[str]:
        """Return tool_call ids from an assistant message."""
        if msg.get("role") != "assistant":
            return []
        tool_calls = msg.get("tool_calls")
        if not isinstance(tool_calls, list):
            return []

        call_ids: List[str] = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                call_id = tc.get("id")
                if call_id:
                    call_ids.append(call_id)
        return call_ids

    def _find_parent_assistant_index(self, tool_call_id: str, before_index: int) -> Optional[int]:
        """Find the assistant message index that created a given tool_call id."""
        if not tool_call_id:
            return None

        for idx in range(before_index, -1, -1):
            if tool_call_id in self._assistant_tool_call_ids(self.conversation[idx]):
                return idx
        return None

    def _sum_message_tokens(self, start: int, end: int) -> int:
        """Token estimate for self.conversation[start:end]."""
        if start >= end:
            return 0
        return sum(self._estimate_message_tokens(msg) for msg in self.conversation[start:end])

    def _is_safe_split_message(self, msg: Dict[str, Any]) -> bool:
        """Safe split starts at user message or assistant message without tool calls."""
        role = msg.get("role")
        if role == "user":
            return True
        if role == "assistant" and not msg.get("tool_calls"):
            return True
        return False

    def _repair_tool_pairs_in_suffix(self, start: int, available_tokens: Optional[int] = None) -> int:
        """Adjust suffix start so tool_call/tool_result pairs stay valid."""
        total = len(self.conversation)
        start = max(0, min(start, total))

        while start < total:
            assistant_by_call_id: Dict[str, int] = {}
            assistant_calls_by_index: Dict[int, List[str]] = {}
            for idx in range(start, total):
                call_ids = self._assistant_tool_call_ids(self.conversation[idx])
                if not call_ids:
                    continue
                assistant_calls_by_index[idx] = call_ids
                for call_id in call_ids:
                    assistant_by_call_id[call_id] = idx

            result_indexes_by_call_id: Dict[str, List[int]] = {}
            orphan_tool_index: Optional[int] = None
            orphan_parent_index: Optional[int] = None
            for idx in range(start, total):
                msg = self.conversation[idx]
                if msg.get("role") != "tool":
                    continue

                tool_call_id = msg.get("tool_call_id")
                if not tool_call_id:
                    orphan_tool_index = idx
                    break

                if tool_call_id not in assistant_by_call_id:
                    orphan_tool_index = idx
                    orphan_parent_index = self._find_parent_assistant_index(tool_call_id, idx - 1)
                    break

                result_indexes_by_call_id.setdefault(tool_call_id, []).append(idx)

            if orphan_tool_index is not None:
                # Prefer pulling in the parent assistant message when budget allows.
                if orphan_parent_index is not None and orphan_parent_index < start:
                    if available_tokens is None:
                        start = orphan_parent_index
                        continue

                    current_tokens = self._sum_message_tokens(start, total)
                    extra_tokens = self._sum_message_tokens(orphan_parent_index, start)
                    if current_tokens + extra_tokens <= available_tokens:
                        start = orphan_parent_index
                        continue

                # If we cannot include the parent, drop the orphaned tool message(s).
                start = orphan_tool_index + 1
                continue

            missing_drop_index: Optional[int] = None
            for assistant_index, call_ids in assistant_calls_by_index.items():
                missing = [call_id for call_id in call_ids if call_id not in result_indexes_by_call_id]
                if not missing:
                    continue

                # Keep pairs consistent by removing this incomplete assistant turn.
                related_result_indexes = [
                    result_index
                    for call_id in call_ids
                    for result_index in result_indexes_by_call_id.get(call_id, [])
                ]
                drop_until = max(related_result_indexes) + 1 if related_result_indexes else assistant_index + 1
                missing_drop_index = drop_until
                break

            if missing_drop_index is not None:
                start = missing_drop_index
                continue

            break

        return start

    MAX_TOOL_RESULT_CHARS = 12000  # ~4000 tokens

    def _truncate_tool_result(self, result: str) -> str:
        """Truncate large tool results to prevent context window bloat."""
        if len(result) <= self.MAX_TOOL_RESULT_CHARS:
            return result
        half = self.MAX_TOOL_RESULT_CHARS // 2
        lines_total = result.count("\n") + 1
        return (result[:half]
                + f"\n\n... [truncated: {lines_total} lines, {len(result):,} chars → keeping first/last portions] ...\n\n"
                + result[-half:])

    def _prepare_messages(self, system_prompt: str) -> list:
        """Build messages list, truncating old messages to fit context window."""
        system_msg = {"role": "system", "content": system_prompt}

        context_window = getattr(self.llm, "context_window", 128000)
        max_tokens = self.llm.max_tokens
        budget = context_window - max_tokens - 1000  # reserve for overhead

        system_tokens = self._estimate_tokens(system_prompt) + 4
        available = budget - system_tokens

        # Walk backwards to keep the most recent messages that fit
        kept: List[Dict[str, Any]] = []
        used = 0
        start_index = len(self.conversation)
        for msg in reversed(self.conversation):
            msg_tokens = self._estimate_message_tokens(msg)
            if used + msg_tokens > available:
                break
            kept.insert(0, msg)
            used += msg_tokens
            start_index -= 1

        # Always keep at least one recent message.
        if not kept and self.conversation:
            kept = [self.conversation[-1]]
            start_index = len(self.conversation) - 1

        if kept:
            # Validate tool_call/tool_result pairs inside the kept suffix.
            start_index = self._repair_tool_pairs_in_suffix(start_index, available_tokens=available)
            kept = self.conversation[start_index:]

        if not kept and self.conversation:
            # Fallback to the latest safe boundary when strict budget trimming removes everything.
            fallback_start = len(self.conversation) - 1
            for idx in range(len(self.conversation) - 1, -1, -1):
                if self._is_safe_split_message(self.conversation[idx]):
                    fallback_start = idx
                    break
            fallback_start = self._repair_tool_pairs_in_suffix(fallback_start)
            kept = self.conversation[fallback_start:]

        trimmed = len(self.conversation) - len(kept)
        if trimmed > 0:
            console.print(f"  [dim]⚠ Trimmed {trimmed} old messages to fit context window "
                          f"({context_window:,} tokens)[/dim]")

        return [system_msg] + kept

    # ── Streaming response ─────────────────────

    def _stream_response(self, messages: list) -> LLMResponse:
        """Stream LLM response, rendering text incrementally via Rich Live panel.
        Supports Ctrl+C graceful interruption and reasoning content display."""
        response: Optional[LLMResponse] = None
        accumulated_text = ""
        accumulated_reasoning = ""
        live: Optional[Live] = None
        # Force unified markdown-capable rendering for all stream profiles,
        # including ultra, to avoid raw markdown tokens leaking to terminal.
        use_plain_stream = False
        plain_stream_started = False
        plain_md_pending = ""
        thinking_notice_shown = False
        reasoning_stream_buffer = ""
        last_reasoning_brief = ""
        interrupted = False
        last_render_at = 0.0
        last_visible_chars = 0

        def _safe_markdown(text: str) -> str:
            """Best-effort sanitize incomplete markdown for live rendering."""
            if not text:
                return text
            # Close unclosed code fences
            fence_count = len(re.findall(r"(?m)^```", text))
            if fence_count % 2 == 1:
                text += "\n```"
            # Close unclosed inline markup (order matters: longest first)
            for marker in ("***", "**", "__"):
                if text.count(marker) % 2 == 1:
                    text += marker
            return text

        def _build_panel(render_markdown: bool = False):
            """Build the display area with thinking summary when available."""
            if accumulated_text:
                if accumulated_text.strip():
                    return Markdown(_safe_markdown(accumulated_text))
                return Text(accumulated_text)
            elif accumulated_reasoning:
                if self.reasoning_display == "off":
                    return Text("  ⏳ thinking…", style="dim")
                reasoning_lines = accumulated_reasoning.strip().splitlines()
                if self.reasoning_display != "full":
                    return Text(
                        f"💭 thinking… ({len(reasoning_lines)} lines)",
                        style="dim",
                    )
                if len(reasoning_lines) > 12:
                    shown = reasoning_lines[-10:]
                    content = f"💭 *thinking… ({len(reasoning_lines)} lines, showing last 10)*\n"
                    content += "\n".join(f"{l}" for l in shown)
                else:
                    content = "💭 *thinking…*\n"
                    content += "\n".join(reasoning_lines)
                return Text(content, style="dim")
            else:
                return Text("  ⏳ thinking…", style="dim")

        def _visible_chars() -> int:
            if accumulated_text:
                return len(accumulated_text)
            return len(accumulated_reasoning)

        def _is_priority_chunk(chunk: str) -> bool:
            if not chunk:
                return False
            # Prefer immediate flush on natural phrase boundaries.
            if any(mark in chunk for mark in ("\n", "。", "！", "？", "；", "：", ".", "!", "?", ";", ":")):
                return True
            return len(chunk) >= max(4, self._stream_profile_setting("min_chars"))

        def _ensure_live() -> None:
            nonlocal live
            if live is not None:
                return
            console.print()
            live = Live(console=console, refresh_per_second=8, auto_refresh=False)
            live.start()

        def _ensure_plain_stream() -> None:
            nonlocal plain_stream_started
            if plain_stream_started:
                return
            if not thinking_notice_shown:
                console.print()
            plain_stream_started = True

        def _sanitize_plain_chunk(chunk: str, *, final: bool = False) -> str:
            nonlocal plain_md_pending
            text = plain_md_pending + (chunk or "")
            plain_md_pending = ""

            if not final and text:
                trailing = ""
                while text and text[-1] in ("*", "_", "`") and len(trailing) < 2:
                    trailing = text[-1] + trailing
                    text = text[:-1]
                plain_md_pending = trailing

            if not text:
                return ""

            text = text.replace("```", "")
            text = text.replace("**", "")
            text = text.replace("__", "")
            text = text.replace("`", "")
            text = re.sub(r"(?m)^\\s{0,3}#{1,6}\\s+", "", text)
            text = re.sub(r"(?m)^\\s*>\\s?", "", text)
            return text

        def _write_plain_text(chunk: str) -> None:
            if not chunk:
                return
            _ensure_plain_stream()
            stream = getattr(console, "file", None)
            if stream is not None and hasattr(stream, "write"):
                stream.write(chunk)
                if hasattr(stream, "flush"):
                    stream.flush()
                return
            console.print(chunk, end="", markup=False, highlight=False, soft_wrap=True)

        def _stream_plain_text(chunk: str) -> None:
            if not chunk:
                return
            cleaned = _sanitize_plain_chunk(chunk)
            if cleaned:
                _write_plain_text(cleaned)

        def _compress_reasoning_line(line: str) -> str:
            compact = " ".join(line.strip().split())
            if not compact:
                return ""
            if len(compact) > 96:
                return compact[:93] + "..."
            return compact

        def _stream_plain_reasoning(chunk: str) -> None:
            nonlocal reasoning_stream_buffer, thinking_notice_shown, last_reasoning_brief
            if self.reasoning_display == "off" or not chunk:
                return

            reasoning_stream_buffer += chunk
            while "\n" in reasoning_stream_buffer:
                line, reasoning_stream_buffer = reasoning_stream_buffer.split("\n", 1)
                brief = _compress_reasoning_line(line)
                if not brief:
                    continue
                if self.reasoning_display == "summary" and brief == last_reasoning_brief:
                    continue

                if not thinking_notice_shown:
                    console.print("\n  [dim]💭 thinking…[/dim]")
                    thinking_notice_shown = True

                message = line.strip() if self.reasoning_display == "full" else brief
                console.print(f"  [dim]💭 {message}[/dim]")
                last_reasoning_brief = brief

        def _flush_plain_reasoning_buffer() -> None:
            nonlocal reasoning_stream_buffer, thinking_notice_shown, last_reasoning_brief
            if self.reasoning_display == "off":
                reasoning_stream_buffer = ""
                return

            brief = _compress_reasoning_line(reasoning_stream_buffer)
            if not brief:
                reasoning_stream_buffer = ""
                return

            if self.reasoning_display == "summary" and brief == last_reasoning_brief:
                reasoning_stream_buffer = ""
                return

            if not thinking_notice_shown:
                console.print("\n  [dim]💭 thinking…[/dim]")
                thinking_notice_shown = True

            message = reasoning_stream_buffer.strip() if self.reasoning_display == "full" else brief
            console.print(f"  [dim]💭 {message}[/dim]")
            last_reasoning_brief = brief
            reasoning_stream_buffer = ""

        def _maybe_render(force: bool = False, final: bool = False, priority: bool = False) -> None:
            nonlocal last_render_at, last_visible_chars
            if live is None:
                return

            visible_chars = _visible_chars()
            if visible_chars < last_visible_chars:
                last_visible_chars = 0

            if not force:
                elapsed = time.monotonic() - last_render_at
                growth = visible_chars - last_visible_chars

                # Time-based fallback: always refresh after max_silent_ms
                max_silent = self._stream_profile_setting("max_silent_ms") / 1000.0
                silent_ready = elapsed >= max_silent and growth > 0

                priority_ready = (
                    priority
                    and growth >= self._stream_profile_setting("priority_chars")
                    and elapsed >= self._stream_profile_setting("priority_interval")
                )
                normal_ready = (
                    growth >= self._stream_profile_setting("min_chars")
                    or elapsed >= self._stream_profile_setting("interval")
                )
                if not silent_ready and not priority_ready and not normal_ready:
                    return

            live.update(_build_panel())
            if hasattr(live, "refresh"):
                live.refresh()
            last_render_at = time.monotonic()
            last_visible_chars = _visible_chars()

        try:
            for event_type, data in self.llm.chat_stream(messages, tools=self.tools.schemas):
                if event_type == "text":
                    accumulated_text += data
                    if use_plain_stream:
                        _flush_plain_reasoning_buffer()
                        _stream_plain_text(data)
                    else:
                        _ensure_live()
                        _maybe_render(priority=_is_priority_chunk(data))
                elif event_type == "reasoning":
                    accumulated_reasoning += data
                    # Show thinking only before primary content appears
                    if not accumulated_text:
                        if use_plain_stream:
                            _stream_plain_reasoning(data)
                        else:
                            _ensure_live()
                            _maybe_render(priority=_is_priority_chunk(data))
                elif event_type == "done":
                    response = data
        except KeyboardInterrupt:
            interrupted = True
            if plain_stream_started:
                console.print()
            # Build a partial response from what we have so far
            content = accumulated_text if accumulated_text else "(interrupted)"
            reasoning = accumulated_reasoning if accumulated_reasoning else None
            if reasoning is not None and not reasoning:
                reasoning = ""
            response = LLMResponse(content=content, reasoning_content=reasoning)
            console.print("\n  [yellow]⚠ Stream interrupted by user[/yellow]")
        except ConnectionError:
            raise
        except Exception as e:
            raise ConnectionError(f"Streaming error: {type(e).__name__}: {e}")
        finally:
            if live is not None:
                _maybe_render(force=True, final=True)
                live.stop()
            elif plain_stream_started:
                _flush_plain_reasoning_buffer()
                tail = _sanitize_plain_chunk("", final=True)
                if tail:
                    _write_plain_text(tail)
                console.print()

            # Show thinking summary after main content (if reasoning was used)
            if accumulated_reasoning and accumulated_text:
                reasoning_lines = accumulated_reasoning.strip().splitlines()
                if self.reasoning_display != "off" and len(reasoning_lines) > 3:
                    console.print(f"  [dim]💭 thinking: {len(reasoning_lines)} lines[/dim]")

        if response is None:
            raise ConnectionError("Stream ended without completion")

        return response

    def _handle_tool_calls(self, response: LLMResponse):
        tc_raw = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
            for tc in response.tool_calls
        ]
        assistant_msg = {
            "role": "assistant", "content": response.content, "tool_calls": tc_raw,
        }
        # DeepSeek Reasoner requires reasoning_content on ALL assistant messages
        if response.reasoning_content is not None:
            assistant_msg["reasoning_content"] = response.reasoning_content
        self.conversation.append(assistant_msg)

        for tc in response.tool_calls:
            self._render_tool_call(tc.name, tc.arguments)

            if not self.auto_confirm and ToolRegistry.needs_confirmation(tc.name):
                if not self._confirm(tc.name, tc.arguments):
                    self.conversation.append({"role": "tool", "tool_call_id": tc.id,
                                              "content": "⚠ User denied."})
                    console.print("  [yellow]↳ skipped[/yellow]")
                    continue

            t0 = time.monotonic()
            result = self.tools.execute(tc.name, tc.arguments)
            elapsed = time.monotonic() - t0
            self._render_result(tc.name, result, elapsed)

            # Handle image results specially for multimodal
            if tc.name == "read_image" and result.startswith("[IMAGE:"):
                self._handle_image_result(tc, result)
                continue

            if tc.name == "web_fetch":
                stored_result = self._summarize_web_for_context(result)
                self.conversation.append({"role": "tool", "tool_call_id": tc.id, "content": stored_result})
                continue

            if tc.name in ToolRegistry.WRITE_TOOLS:
                self._files_modified = True
            # Truncate large tool results in conversation to preserve context window
            stored_result = self._truncate_tool_result(result)
            self.conversation.append({"role": "tool", "tool_call_id": tc.id, "content": stored_result})

    def _summarize_web_for_context(self, result: str) -> str:
        """Store concise web content in context to reduce token pressure."""
        if result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out")):
            return self._truncate_tool_result(result)

        if self.web_display == "full":
            return self._truncate_tool_result(result)

        text = result.strip()
        if not text:
            return result

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""

        first = lines[0]
        start_index = 0
        if first.lower().startswith("url:"):
            header = first
            start_index = 1
        else:
            header = "URL: (not provided)"

        body = lines[start_index:]
        summary_lines: List[str] = []
        consumed = 0
        if self.web_display == "brief":
            max_lines = 1
            max_chars = min(600, max(200, self.web_context_chars // 5))
        else:
            max_lines = max(2, self.web_preview_lines + 2)
            max_chars = self.web_context_chars

        for line in body:
            if consumed >= max_chars:
                break
            remaining = max_chars - consumed
            clipped = line[:remaining]
            summary_lines.append(clipped)
            consumed += len(clipped)
            if len(summary_lines) >= max_lines:
                break

        summary_text = "\n".join(summary_lines)
        omitted_chars = max(0, len("\n".join(body)) - consumed)

        parts = [header]
        if summary_text:
            parts.extend(["", summary_text])
        if omitted_chars > 0:
            parts.append(f"\n... (context summary omitted {omitted_chars:,} chars)")
        return "\n".join(parts)

    def _format_web_result_preview(self, result: str) -> str:
        """Compress web tool output for terminal display."""
        if result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out")):
            return result

        if self.web_display == "full":
            return result

        text = result.strip()
        if not text:
            return result

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return result

        first = lines[0]
        if first.lower().startswith("url:"):
            url = first[4:].strip()
            body_lines = lines[1:]
        else:
            url = "(unknown)"
            body_lines = lines

        body_text = " ".join(body_lines).strip()

        if self.web_display == "brief":
            if not body_text:
                return f"web: {url}"
            snippet_limit = max(80, min(self.web_preview_chars, 180))
            snippet = body_text[:snippet_limit].strip()
            omitted_chars = max(0, len(body_text) - len(snippet))
            tail = f" ... (+{omitted_chars:,} chars)" if omitted_chars > 0 else ""
            return f"web: {url} | {snippet}{tail}"

        preview_lines: List[str] = []
        used_chars = 0
        for line in body_lines:
            if len(preview_lines) >= self.web_preview_lines:
                break
            if used_chars >= self.web_preview_chars:
                break
            remaining = self.web_preview_chars - used_chars
            clipped = line[:remaining].strip()
            if not clipped:
                continue
            preview_lines.append(clipped)
            used_chars += len(clipped)

        omitted_chars = max(0, len(body_text) - used_chars)
        preview = "\n     ".join(preview_lines) if preview_lines else "(no preview)"
        tail = (
            f"\n     ... ({omitted_chars:,} chars omitted)"
            if omitted_chars > 0
            else ""
        )
        return f"web: {url}\n     {preview}{tail}"

    def _confirm(self, tool_name: str, arguments: dict) -> bool:
        try:
            # Show diff preview for file editing operations
            if tool_name == "str_replace":
                self._show_edit_preview(tool_name, arguments)
            elif tool_name == "write_file":
                self._show_write_preview(arguments)
            elif tool_name == "bash":
                cmd = arguments.get("command", "")
                console.print(f"  [dim]command:[/dim] {cmd}")

            ans = console.input("  (y)es / (n)o / (a)lways: ").strip().lower()
            if ans in ("a", "always"):
                self.auto_confirm = True
                return True
            return ans in ("y", "yes", "")
        except (KeyboardInterrupt, EOFError):
            return False

    def _show_edit_preview(self, tool_name: str, arguments: dict):
        """Show diff preview for str_replace."""
        path = arguments.get("path", "")
        old_str = arguments.get("old_str", "")
        new_str = arguments.get("new_str", "")

        can_apply, diff = self.tools.files.preview_str_replace(path, old_str, new_str)
        if can_apply and diff:
            console.print("  [dim]─── diff preview ───[/dim]")
            for line in diff.splitlines()[:30]:
                if line.startswith('+') and not line.startswith('+++'):
                    console.print(f"  [green]{line}[/green]")
                elif line.startswith('-') and not line.startswith('---'):
                    console.print(f"  [red]{line}[/red]")
                elif line.startswith('@@'):
                    console.print(f"  [cyan]{line}[/cyan]")
                else:
                    console.print(f"  [dim]{line}[/dim]")
            if len(diff.splitlines()) > 30:
                console.print(f"  [dim]... ({len(diff.splitlines()) - 30} more lines)[/dim]")
        elif not can_apply:
            console.print(f"  [yellow]⚠ {diff}[/yellow]")

    def _show_write_preview(self, arguments: dict):
        """Show diff preview for write_file."""
        path = arguments.get("path", "")
        content = arguments.get("content", "")

        is_overwrite, diff = self.tools.files.preview_write_file(path, content)
        if is_overwrite and diff:
            console.print("  [dim]─── diff preview ───[/dim]")
            for line in diff.splitlines()[:30]:
                if line.startswith('+') and not line.startswith('+++'):
                    console.print(f"  [green]{line}[/green]")
                elif line.startswith('-') and not line.startswith('---'):
                    console.print(f"  [red]{line}[/red]")
                elif line.startswith('@@'):
                    console.print(f"  [cyan]{line}[/cyan]")
                else:
                    console.print(f"  [dim]{line}[/dim]")
            if len(diff.splitlines()) > 30:
                console.print(f"  [dim]... ({len(diff.splitlines()) - 30} more lines)[/dim]")
        else:
            console.print(f"  [dim]{diff}[/dim]")

    def _handle_image_result(self, tc, result: str):
        """Handle image tool result for multimodal LLM."""
        path = tc.arguments.get("path", "")
        try:
            img_data = self.tools.files.read_image(path)
            # Create multimodal tool result
            content = [
                {"type": "text", "text": f"Image loaded: {path} ({img_data['size']} bytes)"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img_data['media_type']};base64,{img_data['data']}"
                    }
                }
            ]
            self.conversation.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": content
            })
        except Exception as e:
            self.conversation.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": f"Error loading image: {e}"
            })

    # ── Rendering ──────────────────────────────

    def _render_error(self, message: str):
        panel = Panel(
            f"[red]{message}[/red]",
            title="[bold red]Error[/bold red]",
            title_align="left",
            border_style="red",
            padding=(0, 2),
        )
        console.print()
        console.print(panel)

    def _render_tool_call(self, name, args):
        icons = {"read_file": "📖", "create_file": "📝", "write_file": "📝",
                 "str_replace": "✏️ ", "delete_file": "🗑️ ", "list_directory": "📁",
                 "search_files": "🔍", "bash": "💻", "web_fetch": "🌐"}
        icon = icons.get(name, "🔧")

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

        console.print(f"\n  {icon} [bold]{name}[/bold] [dim]{detail}[/dim]")

    def _render_result(self, name, result, elapsed: float = 0):
        if (
            name == "web_fetch"
            and self.web_display != "full"
            and not result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out"))
        ):
            result = self._format_web_result_preview(result)

        lines = result.splitlines()
        time_str = f" [dim]({elapsed:.1f}s)[/dim]" if elapsed >= 0.1 else ""

        # Detect success vs error
        is_error = result.startswith(("⚠", "⛔", "⏱", "Error:", "Blocked:", "Timed out"))
        is_success = any(result.startswith(w) for w in
                         ("Created", "Edited", "Overwrote", "Deleted", "✓", "Found"))

        if is_error:
            preview = result if len(lines) <= 5 else "\n".join(lines[:5]) + f"\n     ... ({len(lines)-5} more)"
            console.print(f"     [red]{preview}[/red]{time_str}")
        elif is_success:
            console.print(f"     [green]✓ {result.splitlines()[0]}[/green]{time_str}")
        else:
            if len(lines) > 20:
                preview = "\n".join(lines[:15]) + f"\n     ... ({len(lines)-15} more lines)"
            else:
                preview = result
            for line in preview.splitlines()[:20]:
                console.print(f"     [dim]{line}[/dim]")
            if time_str:
                console.print(f"     {time_str}")

    def get_stats(self) -> Dict:
        user_msgs = sum(1 for m in self.conversation if m.get("role") == "user")
        tool_calls = sum(len(m.get("tool_calls", []))
                         for m in self.conversation if m.get("role") == "assistant" and m.get("tool_calls"))

        # Context window usage
        context_window = getattr(self.llm, "context_window", 128000)
        conv_tokens = sum(self._estimate_message_tokens(m) for m in self.conversation)
        budget = context_window - self.llm.max_tokens - 1000
        pct = int(conv_tokens / budget * 100) if budget > 0 else 0

        return {
            "messages": len(self.conversation),
            "user_messages": user_msgs,
            "tool_calls": tool_calls,
            "total_tokens": self.total_tokens,
            "context_used": f"~{conv_tokens:,} / {budget:,} ({pct}%)",
            "context_window": f"{context_window:,}",
            "thinking_display": self.reasoning_display,
            "web_display": self.web_display,
            "answer_style": self.answer_style,
        }

    def compact_conversation(self) -> int:
        """Compact old messages into a summary, keeping a safe recent suffix."""
        keep_last = 4
        if len(self.conversation) <= keep_last:
            return 0

        split_index = len(self.conversation) - keep_last
        split_index = self._repair_tool_pairs_in_suffix(split_index)

        # Safe split starts at user, or assistant without tool calls.
        while split_index > 0 and not self._is_safe_split_message(self.conversation[split_index]):
            split_index -= 1

        if split_index <= 0:
            return 0

        old_msgs = self.conversation[:split_index]
        kept = self.conversation[split_index:]

        summary_parts = []
        for msg in old_msgs:
            role = msg.get("role", "?")
            content = (msg.get("content") or "")[:200]
            if role == "user":
                summary_parts.append(f"User: {content}")
            elif role == "assistant":
                tc = msg.get("tool_calls")
                if tc:
                    names = [t["function"]["name"] for t in tc] if isinstance(tc, list) else []
                    summary_parts.append(f"Assistant: called {', '.join(names)}")
                elif content:
                    summary_parts.append(f"Assistant: {content}")
            elif role == "tool":
                summary_parts.append(f"Tool result: {content[:100]}")

        summary_text = (
            "[Conversation summary — earlier messages compacted]\n"
            + "\n".join(summary_parts)
        )
        compacted_count = len(old_msgs)

        self.conversation = [
            {"role": "user", "content": summary_text},
            {"role": "assistant", "content": "Understood. I have the context from our earlier conversation. How can I continue helping?"},
        ] + kept

        return compacted_count

    def reset(self):
        self.conversation.clear()
        self.total_tokens = 0
