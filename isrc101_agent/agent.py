"""Core agent loop with clear visual distinction between user and agent output."""

import json
import time
from typing import List, Dict, Any, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.live import Live

from .llm import LLMAdapter, LLMResponse, build_system_prompt
from .tools import ToolRegistry

console = Console()

# ── Visual theme ───────────────────────────────────
AGENT_BORDER = "cyan"
AGENT_LABEL = "[bold cyan]isrc101[/bold cyan]"
TOOL_BORDER = "dim"


class Agent:
    def __init__(self, llm: LLMAdapter, tools: ToolRegistry, max_iterations: int = 30,
                 auto_confirm: bool = False, chat_mode: str = "code",
                 auto_commit: bool = True, project_instructions: Optional[str] = None):
        self.llm = llm
        self.tools = tools
        self.max_iterations = max_iterations
        self.auto_confirm = auto_confirm
        self.auto_commit = auto_commit
        self.project_instructions = project_instructions
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

    def chat(self, user_message: str) -> str:
        self.conversation.append({"role": "user", "content": user_message})
        self._files_modified = False

        for _ in range(self.max_iterations):
            system = build_system_prompt(self._mode, self.project_instructions)
            messages = self._prepare_messages(system)

            try:
                response = self._stream_response(messages)
            except ConnectionError as e:
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
                return response.content

            console.print("[dim]  (empty response, retrying...)[/dim]")

        msg = f"⚠ Reached max iterations ({self.max_iterations})."
        console.print(f"\n[yellow]{msg}[/yellow]")
        return msg

    # ── Context window management ──────────────

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate: ~3.5 chars per token (mix of EN/CJK)."""
        if not text:
            return 0
        return max(1, len(text) // 3)

    def _estimate_message_tokens(self, msg: dict) -> int:
        """Estimate tokens for a conversation message."""
        tokens = 4  # per-message overhead
        content = msg.get("content", "") or ""
        tokens += self._estimate_tokens(content)
        if "tool_calls" in msg:
            tokens += self._estimate_tokens(json.dumps(msg["tool_calls"]))
        if "reasoning_content" in msg:
            tokens += self._estimate_tokens(msg.get("reasoning_content", "") or "")
        return tokens

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
        kept: List[Dict] = []
        used = 0
        for msg in reversed(self.conversation):
            msg_tokens = self._estimate_message_tokens(msg)
            if used + msg_tokens > available:
                break
            kept.insert(0, msg)
            used += msg_tokens

        # Always keep at least the last user message
        if not kept and self.conversation:
            kept = [self.conversation[-1]]

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
        interrupted = False

        def _build_panel(subtitle=None):
            """Build the display area: thinking内容只在主内容未出现时显示，主内容出现后自动遮挡。"""
            if accumulated_text:
                # 主内容出现后只显示主内容
                md = Markdown(accumulated_text) if accumulated_text.strip() else Text("  ⏳ thinking…", style="dim")
                return md
            elif accumulated_reasoning:
                # 只显示thinking内容（无方框，dim样式）
                reasoning_lines = accumulated_reasoning.strip().splitlines()
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

        try:
            for event_type, data in self.llm.chat_stream(messages, tools=self.tools.schemas):
                if event_type == "text":
                    if live is None:
                        console.print()
                        live = Live(console=console, refresh_per_second=8)
                        live.start()
                    accumulated_text += data
                    live.update(_build_panel())
                elif event_type == "reasoning":
                    if live is None:
                        console.print()
                        live = Live(console=console, refresh_per_second=8)
                        live.start()
                    accumulated_reasoning += data
                    # 只有主内容未出现时才显示thinking
                    if not accumulated_text:
                        live.update(_build_panel())
                elif event_type == "done":
                    response = data
        except KeyboardInterrupt:
            interrupted = True
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
                # 最终只显示主内容（thinking已遮挡）
                live.update(_build_panel())
                live.stop()

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

            if tc.name in ToolRegistry.WRITE_TOOLS:
                self._files_modified = True
            # Truncate large tool results in conversation to preserve context window
            stored_result = self._truncate_tool_result(result)
            self.conversation.append({"role": "tool", "tool_call_id": tc.id, "content": stored_result})

    def _confirm(self, tool_name: str, arguments: dict) -> bool:
        try:
            if tool_name == "bash":
                cmd = arguments.get("command", "")
                console.print(f"  [dim]command:[/dim] {cmd}")
            ans = console.input("  (y)es / (n)o / (a)lways: ").strip().lower()
            if ans in ("a", "always"):
                self.auto_confirm = True
                return True
            return ans in ("y", "yes", "")
        except (KeyboardInterrupt, EOFError):
            return False

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
                 "search_files": "🔍", "bash": "💻"}
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
            case _:
                detail = ""

        console.print(f"\n  {icon} [bold]{name}[/bold] [dim]{detail}[/dim]")

    def _render_result(self, name, result, elapsed: float = 0):
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
            "mode": self._mode,
        }

    def compact_conversation(self) -> int:
        """Compact old conversation messages into a summary, keeping the last 4."""
        if len(self.conversation) <= 4:
            return 0

        # Keep last 4 messages, summarize everything before
        old_msgs = self.conversation[:-4]
        kept = self.conversation[-4:]

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
